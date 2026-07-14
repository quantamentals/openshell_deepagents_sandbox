"""Host-registered tools that run yfinance *inside* the OpenShell sandbox.

These are for exercising sandbox network policy (Yahoo / yfinance allowlist).
They do NOT call Yahoo from the LangGraph host process — traffic goes through
the sandbox egress proxy under policy.yaml.

Prerequisite: sandbox has this repo's policy applied, e.g.
  openshell policy set <name> --policy policy.yaml --wait
  # or recreate: sandbox delete + create --keep --policy policy.yaml
"""

from __future__ import annotations

import json
import os
import textwrap

from langchain_core.tools import tool
from openshell import SandboxClient, SandboxSession

from src.backend import SANDBOX_NAME_ENV

_ENSURE_YFINANCE = textwrap.dedent(
    """\
    import importlib.util
    import subprocess
    import sys

    if importlib.util.find_spec("yfinance") is None:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "yfinance"],
        )
    """
)


def _sandbox_session() -> SandboxSession:
    client = SandboxClient.from_active_cluster()
    name = os.environ.get(SANDBOX_NAME_ENV)
    if not name:
        raise RuntimeError(
            f"{SANDBOX_NAME_ENV} must be set so yfinance tools hit a known "
            "sandbox (needed to test policy)."
        )
    ref = client.get(name)
    return SandboxSession(client, ref)


def _run_in_sandbox(python_source: str, *, timeout_seconds: int = 120) -> str:
    """Execute Python in the OpenShell sandbox; return stdout+stderr."""
    session = _sandbox_session()
    script = _ENSURE_YFINANCE + "\n" + python_source
    result = session.exec(
        ["python3", "-c", script],
        timeout_seconds=timeout_seconds,
    )
    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    body = "\n".join(parts).strip() or "(no output)"
    if result.exit_code != 0:
        return (
            f"ERROR exit_code={result.exit_code}\n{body}\n\n"
            "If you see CONNECT/403/proxy errors, the sandbox policy likely "
            "blocks Yahoo or PyPI — apply policy.yaml to the sandbox "
            "(see docs/openshell-policy-tutorial.md)."
        )
    return body


@tool
def yfinance_quote(symbol: str) -> str:
    """Fetch a latest price / quote summary for a ticker via yfinance in the OpenShell sandbox.

    Use this to verify Yahoo Finance network policy. Symbol examples: AAPL, MSFT, SPY.
    """
    sym = symbol.strip().upper()
    src = textwrap.dedent(
        f"""\
        import json
        import yfinance as yf

        t = yf.Ticker({sym!r})
        price = None
        try:
            price = float(t.fast_info.last_price)
        except Exception:
            info = t.info or {{}}
            price = info.get("regularMarketPrice") or info.get("currentPrice")
        out = {{
            "symbol": {sym!r},
            "last_price": price,
            "currency": getattr(t.fast_info, "currency", None),
            "source": "openshell-sandbox-yfinance",
        }}
        print(json.dumps(out, default=str))
        """
    )
    return _run_in_sandbox(src)


@tool
def yfinance_history(symbol: str, period: str = "5d", interval: str = "1d") -> str:
    """Download OHLCV history for a ticker via yfinance in the OpenShell sandbox.

    period examples: 1d, 5d, 1mo, 3mo, 1y. interval examples: 1d, 1h.
    Returns JSON records (capped) so you can confirm Yahoo data egress works under policy.
    """
    sym = symbol.strip().upper()
    src = textwrap.dedent(
        f"""\
        import json
        import yfinance as yf

        df = yf.download(
            {sym!r},
            period={period!r},
            interval={interval!r},
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            print(json.dumps({{"symbol": {sym!r}, "rows": 0, "data": []}}))
        else:
            flat = df.reset_index()
            # Flatten MultiIndex columns if present
            flat.columns = [
                c[0] if isinstance(c, tuple) else c for c in flat.columns
            ]
            records = json.loads(
                flat.tail(30).to_json(orient="records", date_format="iso")
            )
            print(json.dumps({{
                "symbol": {sym!r},
                "period": {period!r},
                "interval": {interval!r},
                "rows": len(flat),
                "data": records,
                "source": "openshell-sandbox-yfinance",
            }}, default=str))
        """
    )
    return _run_in_sandbox(src, timeout_seconds=180)


@tool
def yfinance_info(symbol: str) -> str:
    """Fetch selected ticker info fields via yfinance in the OpenShell sandbox (policy probe)."""
    sym = symbol.strip().upper()
    keys = [
        "shortName",
        "longName",
        "sector",
        "industry",
        "exchange",
        "currency",
        "regularMarketPrice",
        "marketCap",
        "trailingPE",
    ]
    src = textwrap.dedent(
        f"""\
        import json
        import yfinance as yf

        info = yf.Ticker({sym!r}).info or {{}}
        keys = {json.dumps(keys)}
        out = {{"symbol": {sym!r}, "source": "openshell-sandbox-yfinance"}}
        for k in keys:
            if k in info:
                out[k] = info[k]
        print(json.dumps(out, default=str))
        """
    )
    return _run_in_sandbox(src)


YFINANCE_TOOLS = [yfinance_quote, yfinance_history, yfinance_info]
