# Reusing this OpenShell + Deep Agents stack in another project

This repo is a **template**, not a library you `pip install` as-is. To reuse it elsewhere, copy the glue you need, add the same Python deps, and keep a working OpenShell gateway + sandbox + policy.

---

## What you actually need (layers)

```text
Always (runtime outside your Python tree)
  Docker Desktop
  openshell CLI (from the openshell package)
  gateway start → Connected
  sandbox create --keep --policy <your-policy.yaml>
  OPENSHELL_SANDBOX_NAME (or create-on-the-fly)

Minimal Python glue (sandbox for deepagents)
  backend.py pattern → OpenShellBackend + create_backend

Optional agent harness
  agent.py + prompts + AGENTS.md + tools.py

Optional Studio
  langgraph.json + .env + langgraph-cli

Optional docs / policy you edit per product
  policy.yaml (almost always — product-specific allowlists)
```

Gateway and sandboxes are **global to your machine** (OpenShell config under `~/.config/openshell/`). You do **not** need to reinstall OpenShell for each project — but each project should bring its own `policy.yaml` (and usually its own sandbox name).

---



## Directory checklist — copy vs skip


| Path in this repo                     | Copy?                      | Why                                                                   |
| ------------------------------------- | -------------------------- | --------------------------------------------------------------------- |
| `src/backend.py`                      | **Yes (core)**             | OpenShell ↔ deepagents adapter                                        |
| `policy.yaml`                         | **Yes (start from this)**  | Edit network/FS for the new app; apply with `--policy`                |
| `src/agent.py`                        | Usually                    | Example `create_deep_agent` wiring                                    |
| `src/prompts.py`                      | Usually                    | System prompt (rewrite for the new domain)                            |
| `src/AGENTS.md`                       | Optional                   | Host memory file; path must match `memory=[...]` + CompositeBackend   |
| `src/tools.py`                        | Optional                   | Example host tools that exec **inside** the sandbox (yfinance probes) |
| `langgraph.json`                      | If using Studio            | Point `graphs` at your module:`variable`                              |
| `.env` **/** `.env.example`           | Yes (don’t commit secrets) | `OPENSHELL_SANDBOX_NAME`, `OLLAMA_`*, LangSmith                       |
| `pyproject.toml` **deps**             | Yes (merge)                | See [Dependencies](#dependencies-pyproject)                           |
| `docs/`                               | Optional                   | Reference only                                                        |
| `README.md`, `sandbox.py`, `outputs/` | No                         | Examples / clutter                                                    |
| `.venv/`, `.langgraph_api/`           | No                         | Local state                                                           |


Minimal new-project tree:

```text
my-app/
  pyproject.toml          # deepagents, openshell, langchain-*, …
  policy.yaml             # your allowlists
  .env                    # OPENSHELL_SANDBOX_NAME=…
  langgraph.json          # optional Studio
  src/
    __init__.py
    backend.py            # from this repo (adjust imports/package name)
    agent.py              # create_deep_agent(..., backend=create_backend)
    prompts.py            # optional
    AGENTS.md             # optional if you use memory=
    tools.py              # optional custom tools
```

If you rename `src` → something else (e.g. `my_agent`), change **all** imports and `langgraph.json` / `memory` routes accordingly.

---



## Dependencies (`pyproject`)

Minimum for OpenShell + deepagents sandbox:

```toml
dependencies = [
    "deepagents>=0.4.11",
    "openshell>=0.0.13",
    "langchain>=1.2.12",
]
```

Add as needed:


| Extra                    | When                                                                                       |
| ------------------------ | ------------------------------------------------------------------------------------------ |
| `langchain-ollama`       | Same Ollama/Nemotron model wiring as this repo                                             |
| `langgraph-cli[inmem]`   | `uv run langgraph dev --allow-blocking`                                                    |
| `yfinance`               | Only if host or sandbox tooling imports it; sandbox can `pip install` under policy instead |
| `langchain-mcp-adapters` | If you add host MCP tools                                                                  |


Install OpenShell CLI into the venv via the `openshell` package (`uv sync` / `uv run openshell …`).

---



## Imports you’ll use



### Core (required pattern)

```python
# backend (copied/adapted from this repo)
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.sandbox import BaseSandbox
from openshell import SandboxClient, SandboxSession

# agent
from deepagents import create_deep_agent
from my_pkg.backend import create_backend   # wherever you put create_backend
```



### This repo’s module paths today

```python
from src.backend import create_backend, OpenShellBackend, SANDBOX_NAME_ENV
from src.agent import agent                 # CompiledStateGraph
from src.tools import YFINANCE_TOOLS        # optional
from src.prompts import AGENT_INSTRUCTIONS  # optional
```



### Wire a deep agent

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model,                       # ChatOllama, ChatOpenAI, …
    system_prompt="...",
    memory=["/memory/AGENTS.md"],    # optional; needs CompositeBackend route
    tools=[...],                       # optional host tools
    backend=create_backend,            # factory — OpenShell session
)
```



### Without Deep Agents (`create_agent`)

Copy only session helpers / `OpenShellBackend.execute` usage and expose `@tool`s yourself — there is no `backend=` on `create_agent`.

### Programmatic run (no Studio)

```python
from src.agent import agent  # or my_pkg.agent

result = agent.invoke({
    "messages": [{"role": "user", "content": "uname -a in the sandbox"}]
})
```

Ensure env vars are loaded (`OPENSHELL_SANDBOX_NAME`, model keys) before import/invoke.

---



## What `create_backend` expects

From this repo’s `backend.py`:

1. `SandboxClient.from_active_cluster()` — active gateway (`openshell gateway select` / `OPENSHELL_GATEWAY`).
2. `OPENSHELL_SANDBOX_NAME` — if set, `client.get(name)`; else `client.create()` + `wait_ready`.
3. `CompositeBackend` — default = OpenShell; `/memory/` → `./src`, `/skills/` → `./skills`.

When reusing:

- Point `FilesystemBackend(root_dir=...)` at **your** memory/skills dirs (or drop those routes).
- Keep `OPENSHELL_SANDBOX_NAME` in the new project’s `.env`.
- Sandbox name need not be shared across projects (cleaner: one sandbox per product).

---



## Policy / OpenShell for the new project

1. Copy `policy.yaml` and **trim or extend** `network_policies` for that app.
2. Create (or recreate) a sandbox with that file:
  ```bash
   uv run openshell sandbox create --name my-app-sandbox --keep --policy policy.yaml
  ```
3. Set `OPENSHELL_SANDBOX_NAME=my-app-sandbox` in the new `.env`.
4. Editing YAML alone does nothing — see [openshell-policy-tutorial.md](openshell-policy-tutorial.md).

Host-only tools (MCP on the LangGraph process) **do not** use this policy. Sandbox `execute` / tools that call `SandboxSession.exec` **do**.

---



## Studio in another repo

`langgraph.json`:

```json
{
  "dependencies": ["."],
  "graphs": {
    "deepagent": "./src/agent.py:agent"
  },
  "env": ".env"
}
```

Adjust the path if your package layout differs. Then:

```bash
uv run langgraph dev --allow-blocking
```

---



## Reuse recipes


| Goal                                               | Take                                                                                            |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Smallest** — “deepagents runs code in OpenShell” | `backend.py` + deps + gateway/sandbox/policy + `create_deep_agent(..., backend=create_backend)` |
| **Same as this demo**                              | Above + `agent.py`, `prompts.py`, `AGENTS.md`, `langgraph.json`, `.env`                         |
| **Custom tools testing policy**                    | Pattern from `tools.py` (`SandboxSession.exec` inside `@tool`) + matching `network_policies`    |
| **No deepagents**                                  | `openshell` SDK only; wrap `exec` in your own tools                                             |
| **CLI UX**                                         | Your own loop around `agent.invoke` — not the global `deepagents` / `dcode` binaries            |


---



## What not to assume is portable

- **Global** `deepagents` **CLI** will not load your copied `agent.py`.
- **Sandbox** `/sandbox` **files** do not copy with the git repo — use `sandbox download` / `upload`.
- **Gateway** is machine-local; after `gateway destroy`, recreate sandboxes.
- `yfinance` **in** `pyproject.toml` is for the host venv; in-sandbox installs still need `pypi` **(+ Yahoo) policy**.

---



## Quick port checklist

1. New project: Python ≥ 3.12, merge deps, `uv sync`.
2. Copy `src/backend.py` (fix package imports).
3. Copy/adapt `agent.py` (model + prompt + `backend=create_backend`).
4. Copy and edit `policy.yaml`; create sandbox with `--policy`.
5. Set `.env` → `OPENSHELL_SANDBOX_NAME`, model vars.
6. Optional: `langgraph.json` for Studio; optional: `tools.py`.
7. Smoke: `invoke` or Studio → `execute("uname -a")` or a network tool under policy.

---



## Related

- [Components & ways to run](openshell-deep-agents.md)
- [Policy tutorial](openshell-policy-tutorial.md)
- [OpenShell CLI](openshell-cli.md)
- Root [README](../README.md) — host vs sandbox, persistence

