# OpenShell + Deep Agents — components and how to run

This repo wires three products together. Use this doc for **what each piece is**, **how policy works**, and **which run path to pick**. For raw OpenShell CLI commands, see [openshell-cli.md](openshell-cli.md). The root [README](../README.md) has longer operational detail (timeouts, policy playbooks, persistence).

---

## Stack (mental model)

```text
┌─ Your front-end ─────────────────────────────────────────────┐
│  langgraph dev (Studio)  │  custom Python CLI  │  scripts     │
│  (NOT the global `deepagents` CLI — see below)                │
└──────────────────────────────┬────────────────────────────────┘
                               │ tools / invoke
┌──────────────────────────────▼────────────────────────────────┐
│  create_deep_agent  (deepagents library in src/agent.py)      │
│  tools: execute, write_file, read_file, …                     │
│  backend factory → create_backend()                           │
└───────────────┬─────────────────────────────┬─────────────────┘
                │ default paths               │ /memory/, /skills/
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────┐
│  OpenShellBackend         │   │  FilesystemBackend (host)   │
│  SandboxSession.exec …    │   │  ./src , ./skills           │
└─────────────┬─────────────┘   └─────────────────────────────┘
              │ gRPC
              ▼
┌───────────────────────────┐
│  OpenShell gateway        │  ← Docker runs *this* (k3s cluster)
│  https://127.0.0.1:8080     │
└─────────────┬─────────────┘
              │
              ▼
┌───────────────────────────┐
│  Sandbox pod              │  ← code actually runs here
│  policy.yaml enforced     │
│  writable: /sandbox       │
└───────────────────────────┘
```

**OpenShell is not a Docker CLI wrapper.** Docker only hosts the gateway. Agents talk to the OpenShell SDK / gateway (gRPC). Policy is enforced in the sandbox/gateway path — prompt text cannot override it.

---

## Repo components

| Piece | Role |
|-------|------|
| **Docker Desktop** | Engine that runs the OpenShell gateway container. |
| **OpenShell gateway** | Control plane. `openshell gateway start` → Connected on `:8080`. |
| **Sandbox** | Named workload (`openshell sandbox create …`). Agent exec lands here. |
| **`policy.yaml`** | Filesystem + network allowlist **baked into the sandbox** at create (or `policy set` if supported). |
| **`openshell` CLI + SDK** | Manage gateway/sandbox; SDK = `SandboxClient` / `SandboxSession`. |
| **`src/backend.py`** | Adapts an OpenShell session to deepagents’ `BaseSandbox` / `CompositeBackend`. |
| **`src/agent.py`** | `create_deep_agent(..., backend=create_backend)` + Ollama model. |
| **`src/prompts.py`** | System instructions for the agent. |
| **`src/AGENTS.md`** | Host-side memory file (routed via `/memory/`). |
| **`langgraph.json`** | Points LangGraph at `./src/agent.py:agent` and loads `.env`. |
| **`.env`** | `OPENSHELL_SANDBOX_NAME`, `OLLAMA_*`, LangSmith, etc. |

### What `backend.py` does

- **`OpenShellBackend`** — implements `execute`, `upload_files`, `download_files`. Other file tools inherit from deepagents `BaseSandbox` and become shell commands via `execute()`.
- **`create_backend(runtime)`** — factory called once per process:
  - If `OPENSHELL_SANDBOX_NAME` is set → `client.get(name)` (must exist and be Ready).
  - Else → `client.create()` + `wait_ready` (ephemeral sandbox).
  - Returns `CompositeBackend`: default = OpenShell; `/memory/` and `/skills/` stay on the **host** so they persist in git.

`backend.py` does **not** load `policy.yaml`. Policy is already on the sandbox object.

---

## Policy (`policy.yaml`)

**Hands-on tutorial (set / update / verify):** [openshell-policy-tutorial.md](openshell-policy-tutorial.md)

Policy is the **security layer inside the sandbox**, not LangChain middleware.

| Section | Controls |
|---------|----------|
| `filesystem_policy` | `read_only` / `read_write` paths (e.g. write under `/sandbox`) |
| `landlock` / `process` | How FS rules apply; run-as user/group |
| `network_policies` | Named bundles of **host+port** **and** allowed **binaries** |

Outbound traffic is allowed only when both destination and binary match. Miss → often `CONNECT … 403`. Fix: edit YAML, then **recreate** with `--policy` (or `policy set --wait` if your gateway implements it). Editing the file alone does nothing.

```bash
openshell sandbox delete <name>
openshell sandbox create --name <name> --keep --policy policy.yaml
openshell sandbox get <name>          # confirm Phase: Ready + policy dump
openshell logs <name> --since 10m     # dst_host / binary= / deny_reason
```

---

## Two products named “deepagents” (plus `dcode`)

Easy to confuse:

| Product | What it is | OpenShell / this repo? |
|---------|------------|------------------------|
| **`deepagents` library** (`create_deep_agent`) | SDK used by **this repo** in `src/agent.py` | Yes — `backend=create_backend` |
| **`deepagents` CLI** | Batteries-included terminal coding agent (`deepagents` on PATH) | **No** by default — host cwd; optional remote `--sandbox` |
| **`dcode` (Deep Agents Code)** | LangChain’s terminal coding agent on the same SDK family; Nemotron blueprints often run it under **NemoClaw / OpenShell** | Separate install/path — not this repo’s `langgraph dev` graph |

Activating this repo’s `.venv` does **not** make `deepagents` load `src/agent.py`. There is typically **no** `.venv/bin/deepagents`; the shell finds the global CLI. That CLI’s `--agent` means “named prompt/skills profile”, not “load my Python graph”.

---

## Four ways to run (compare)

| # | What | Command / entry | Model (typical) | Isolation | LangSmith / Studio |
|---|------|-----------------|-----------------|-----------|-------------------|
| **A** | **This custom OpenShell deep agent** + LangGraph | `uv run langgraph dev --allow-blocking` | Ollama / `nemotron-3-super:cloud` via `.env` | **OpenShell** + `policy.yaml` | Studio at LangSmith URL; traces if `LANGSMITH_*` set |
| **B** | **Same graph, programmatic** | `agent.invoke(...)` / `ainvoke` in Python | Same as A | Same OpenShell | Traces if LangSmith env set; **no** Studio unless you also run A |
| **C** | **Standard Deep Agents CLI** (batteries included) | `deepagents` (optionally `-n '…'`, `-a name`, `-M model`) | Whatever CLI default / `-M` / `~/.deepagents/config.toml` | Host directory (“unboxed”) unless `--sandbox …` | CLI may open traces; **not** this repo’s graph |
| **D** | **`dcode` + Nemotron** (Deep Agents Code) | `dcode` / `dcode -n '…'` (often after NemoClaw install) | Nemotron (and other models per blueprint) | NemoClaw/OpenShell in NVIDIA blueprints; plain `dcode` can be local | Per dcode/NemoClaw docs — **different product** from A/B |

**Rule of thumb:** A and B are **this repository**. C is the generic terminal agent. D is LangChain Deep Agents Code (and NVIDIA’s Nemotron/OpenShell packaging of it) — complementary, not a substitute for `src/agent.py`.

---

## A — Custom deep agent + LangSmith Studio (`langgraph dev`)

Prerequisites: Docker, gateway Connected, sandbox Ready, `.env` with matching `OPENSHELL_SANDBOX_NAME` and Ollama/LangSmith vars.

```bash
cd /path/to/openshell-deepagent
# gateway + sandbox already running; policy baked at create time
uv run langgraph dev --allow-blocking
```

What happens:

- Loads `langgraph.json` → `./src/agent.py:agent` and `.env`
- Serves API at **http://127.0.0.1:2024**
- Opens **LangSmith Studio** (browser) pointed at that `baseUrl`
- With `LANGSMITH_API_KEY` / `LANGSMITH_TRACING=true`, runs show up in your LangSmith project

`--allow-blocking` is required so OpenShell sync `exec` can run in this stack.

Restart the server after changing `.env` (e.g. sandbox name).

---

## B — Same agent, programmatic `invoke`

Same OpenShell + policy + `create_deep_agent` graph — no Studio process.

```python
# Ensure OPENSHELL_* / OLLAMA_* / LANGSMITH_* are in the environment
# (export them, or load_dotenv(".env"))

from src.agent import agent

result = agent.invoke({
    "messages": [{"role": "user", "content": "Run uname -a in the sandbox"}]
})
print(result["messages"][-1].content)
```

Use for scripts, CI smoke tests, or a **custom CLI** that wraps `invoke` / streaming. Gateway and Ready sandbox still required.

Async: `await agent.ainvoke(...)`. Embed the same object as a subgraph/node in a larger LangGraph app.

---

## C — Standard Deep Agents in the terminal (`deepagents`)

Batteries-included coding agent for the **current directory** — not this repo’s OpenShell backend.

```bash
cd /some/project
deepagents                          # interactive TUI
deepagents -n 'Summarize README.md' # one-shot
deepagents -a custom_agent -M ollama:nemotron-3-super:cloud
deepagents --sandbox <type> …       # optional remote sandbox providers
```

Customization: `~/.deepagents/<name>/AGENTS.md` + skills — **not** `tools=[my_python_fn]` from this repo. Does not read `policy.yaml` or `OPENSHELL_SANDBOX_NAME`.

---

## D — Nemotron with `dcode` (Deep Agents Code)

[`dcode`](https://docs.langchain.com/oss/python/deepagents/cli/overview) is Deep Agents Code — LangChain’s terminal coding agent on the Deep Agents SDK. NVIDIA packages it with **Nemotron** and governed OpenShell via **NemoClaw** blueprints.

**Vanilla Deep Agents Code (host / your own setup):**

```bash
curl -LsSf https://langch.in/dcode | bash   # install once
dcode
dcode -n "Explain this repository"
```

**NVIDIA NemoClaw + Deep Agents Code (Nemotron + OpenShell-style sandbox)** — see [NemoClaw Deep Agents quickstart](https://docs.nvidia.com/nemoclaw/user-guide/deepagents/get-started/quickstart):

```bash
export NEMOCLAW_AGENT=langchain-deepagents-code
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
# then onboard / connect per NemoClaw docs, and inside the sandbox:
dcode
# or: dcode -n "Modernize this repository"
```

That path is NVIDIA’s governed blueprint (Nemotron + OpenShell runtime). It is **not** the same process as `uv run langgraph dev` on **this** repo, even though both involve deep agents + sandboxes. Use **A/B** for this codebase’s `OpenShellBackend` + `policy.yaml`; use **D** when you want the official dcode / NemoClaw coding agent experience.

---

## Ways to run **this** OpenShell agent (A / B only)

Prerequisite every time:

```bash
# Docker up
openshell gateway start
openshell status                                   # Connected
openshell sandbox create --name <name> --keep --policy policy.yaml   # once
# wait Ready (create may time out at 300s while pull continues — poll get/list)
```

Match `.env`:

```bash
OPENSHELL_SANDBOX_NAME=<name>   # must exist or you get gRPC NOT_FOUND "sandbox not found"
```

Then choose **A** (`langgraph dev`) or **B** (`invoke`). For terminal UX without Studio, wrap **B** in your own CLI — do not expect the global `deepagents` / `dcode` binaries to load `src/agent.py`.

---

## `create_deep_agent` vs `create_agent`

| API | Sandbox hook | Custom tools |
|-----|--------------|--------------|
| **`create_deep_agent(..., backend=…)`** | Yes — `backend=` supplies execute/filesystem tools | `tools=[…]` **plus** built-in deepagents tools |
| **`langchain.agents.create_agent(..., tools=…)`** | No `backend=` | You pass tools that call OpenShell yourself |

Example for a plain LangGraph-style agent:

```python
from langchain.agents import create_agent
from src.backend import OpenShellBackend  # + build SandboxSession yourself

@tool
def execute(command: str) -> str:
    """Run a command in the OpenShell sandbox."""
    return backend.execute(command).output

agent = create_agent(model, tools=[execute, ...])
```

Same gateway/sandbox/policy underneath; different harness.

---

## Custom tools and modules

| Surface | Add `@tool` / callables / imports? |
|---------|------------------------------------|
| **This repo + `create_deep_agent`** | Yes — `tools=[my_tool, …]` in `src/agent.py` (or a fork) |
| **Custom CLI wrapping `agent`** | Yes — extend the graph, or add tools before `create_deep_agent` |
| **Global `deepagents` CLI** | No arbitrary Python modules — prompts, skills, MCP; not your `.py` tools |

Host tools (MCP, LangChain tools registered on the graph) run on the **host**. Shell/`write_file` on default paths run in the **sandbox** under policy.

---

## Where agent scripts live (and how to download)

Agent `write_file` / `execute` under the **default** backend write into the **OpenShell sandbox**, not your laptop repo.

| Path the agent uses | Where it actually is | On your machine? |
|---------------------|----------------------|------------------|
| `/sandbox/...` | Writable dir **inside the sandbox pod** | **No** until you download |
| `/tmp/...` | Sandbox ephemeral temp | **No** |
| `/memory/...` | Host `./src/...` (CompositeBackend) | **Yes** — git-friendly |
| `/skills/...` | Host `./skills/...` | **Yes** |

**Convention in this repo:** ask the agent to put scripts under `/sandbox/` (e.g. `/sandbox/outputs/analysis.py`).

### Pull a file to your machine

```bash
# Replace name/paths as needed
SANDBOX=michael-shell

# One file → current directory
uv run openshell sandbox download "$SANDBOX" /sandbox/foo.py .

# One file → a local folder
mkdir -p outputs
uv run openshell sandbox download "$SANDBOX" /sandbox/foo.py ./outputs/
```

### Push a local file into the sandbox

```bash
uv run openshell sandbox upload "$SANDBOX" ./local_script.py /sandbox/local_script.py
```

### Inspect without downloading

```bash
uv run openshell sandbox connect "$SANDBOX"
# then: ls -la /sandbox
```

**Deleting or recreating** the sandbox (e.g. to apply new `policy.yaml`) **wipes `/sandbox`**. Download first if you care about the files. Host `/memory/` and `/skills/` paths are unaffected.

---

## End-to-end checklist

1. Docker Desktop running → `docker info` OK from WSL if you use WSL.
2. `openshell gateway start` → `openshell status` = **Connected**.
3. Create sandbox **with** `--policy policy.yaml` (otherwise you get a default-ish policy).
4. Poll `openshell sandbox get <name>` until **Phase: Ready**.
5. Set `OPENSHELL_SANDBOX_NAME` to that name (restart `langgraph dev` after `.env` changes).
6. Run Studio **or** your custom CLI / `agent.invoke`.
7. Smoke: ask the agent to `uname -a` / write `/sandbox/hello.py` and run it.

---

## Common failure modes (from local use)

| Symptom | Meaning | Fix |
|---------|---------|-----|
| `Socket not found: /var/run/docker.sock` | Docker not reachable from this environment | Start Docker Desktop; ensure WSL integration |
| `sandbox provisioning timed out after 300s` / `Pending` | CLI wait expired; create already registered | Poll `sandbox get` — often becomes Ready after image pull |
| `UNIQUE constraint failed: … name` | Name already exists from a prior create | `sandbox get` / `list`; don’t recreate same name — or `delete` then create |
| `NOT_FOUND` / `sandbox not found` | `.env` name ≠ any sandbox on gateway | Align `OPENSHELL_SANDBOX_NAME` with `sandbox list` |
| `CONNECT … 403` / network deny | Policy host or binary mismatch | Logs → update `policy.yaml` → recreate sandbox |
| Global `deepagents` ignores OpenShell | Different product | Use `langgraph dev` or custom CLI on `src.agent` |

---

## Quick decision guide

```text
This repo’s OpenShell agent + LangSmith Studio?
  → A: uv run langgraph dev --allow-blocking

Same agent in scripts / my own CLI?
  → B: from src.agent import agent; agent.invoke(...)

Batteries-included terminal agent on my laptop folder?
  → C: deepagents

Nemotron terminal coding agent (dcode / NemoClaw blueprint)?
  → D: dcode   (or NemoClaw install + dcode inside sandbox)

Need this repo’s policy.yaml + OpenShellBackend?
  → A or B only
```

---

## Related docs

- [OpenShell policy tutorial](openshell-policy-tutorial.md) — **set and update policy**
- [OpenShell CLI guide](openshell-cli.md) — full CLI map
- [Components & ways to run](openshell-deep-agents.md) — stack / run modes
- [README](../README.md) — full setup, persistence, troubleshooting
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview) — `create_deep_agent` SDK
- [Deep Agents Code (`dcode`)](https://docs.langchain.com/oss/python/deepagents/cli/overview) — terminal coding agent (path **D**)
- [NemoClaw + Deep Agents quickstart](https://docs.nvidia.com/nemoclaw/user-guide/deepagents/get-started/quickstart) — Nemotron + OpenShell packaging of dcode
- [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)
