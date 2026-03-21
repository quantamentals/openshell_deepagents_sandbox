# OpenShell Deep Agent

A general-purpose coding agent that runs inside an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, orchestrated by [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) and powered by [Ollama](https://ollama.com) (default model: `nemotron-3-super:cloud` via LangChain). The agent writes and executes code in an isolated, policy-governed Linux environment — no cloud dependency required for the sandbox itself.

## Table of contents

- [What is OpenShell?](#what-is-openshell)
- [What are Deep Agents?](#what-are-deep-agents)
- [Architecture](#architecture)
- [OpenShell: comprehensive guide](#openshell-comprehensive-guide)
  - [Typical local progression](#typical-local-progression)
  - [Explicit: `sandbox create`, 300s timeout, and polling](#explicit-sandbox-create-300s-timeout-and-polling)
  - [Explicit: after `gateway destroy` (you must recreate sandboxes)](#explicit-after-gateway-destroy-you-must-recreate-sandboxes)
  - [Logging into a sandbox](#logging-into-a-sandbox)
  - [Sandbox CLI cheat sheet](#sandbox-cli-cheat-sheet)
  - [Beyond the CLI](#beyond-the-cli)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running the agent: LangGraph CLI, Deep Agents CLI, and embedding in code](#running-the-agent-langgraph-cli-deep-agents-cli-and-embedding-in-code)
- [Try it out](#try-it-out)
- [Using your sandbox (in depth)](#using-your-sandbox-in-depth)
  - [Agent server lifetime vs gateway vs sandbox (practical reuse)](#agent-server-lifetime-vs-gateway-vs-sandbox-practical-reuse)
  - [Host harness vs sandbox (tools, skills, memory, MCP)](#host-harness-vs-sandbox-tools-skills-memory-mcp)
  - [Docker: stop vs delete, and what persists](#docker-stop-vs-delete-and-what-persists)
  - [Host and sandbox file transfer (restore, upload at create)](#host-and-sandbox-file-transfer-restore-upload-at-create)
- [Model Configuration](#model-configuration)
- [Policy usage flow (gateway, sandbox, and YAML)](#policy-usage-flow-gateway-sandbox-and-yaml)
- [Policy Iteration](#policy-iteration)
- [Allowing new outbound destinations (playbook)](#allowing-new-outbound-destinations-playbook)
- [Useful commands](#useful-commands)
  - [Full local reset (gateway and sandboxes)](#full-local-reset-gateway-and-sandboxes)
- [Troubleshooting](#troubleshooting)
  - [ExecSandbox / SSH transport failures](#execsandbox--ssh-transport-failures)
- [Resources](#resources)

## What is OpenShell?

[OpenShell](https://github.com/NVIDIA/OpenShell) is like a browser's security model, but for agent code execution. It's an on-prem sandbox that lets agents write and run code while enforcing **policies** that control filesystem access, network access, and process permissions. Think of it as a more secure Docker container — the agent can self-evolve and learn new skills, but it can't be tricked into leaking data or running destructive commands.

This matters for LangChain because deep agents connect to real data sources (Linear, Slack, Salesforce). You want the agent to learn new things on the fly, but you don't want to rely on prompt instructions alone to prevent misuse — something external to the agent has to enforce security, which is what OpenShell does.

## What are Deep Agents?

The easiest way to start building agents and applications powered by LLMs — with built-in capabilities for task planning, file systems for context management, subagent-spawning, and long-term memory. You can use deep agents for any task, including complex, multi-step tasks.

We think of deepagents as an "agent harness". It is the same core tool calling loop as other agent frameworks, but with built-in tools and capabilities.

deepagents is a standalone library built on top of LangChain's core building blocks for agents. It uses the LangGraph runtime for durable execution, streaming, human-in-the-loop, and other features.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  LangGraph Dev Server (http://127.0.0.1:2024)       │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │  Deep Agent (Ollama / Nemotron)               │  │
│  │                                               │  │
│  │  Tools: execute, write_file, read_file,       │  │
│  │         edit_file, glob, grep, ls             │  │
│  └──────────┬────────────────────┬───────────────┘  │
│             │                    │                   │
│  ┌──────────▼──────────┐  ┌─────▼────────────────┐  │
│  │  OpenShellBackend   │  │  FilesystemBackend   │  │
│  │                     │  │                      │  │
│  │  Code execution     │  │  /memory/AGENTS.md   │  │
│  │  runs in isolated   │  │  /skills/*.md        │  │
│  │  sandbox container  │  │                      │  │
│  │  via gRPC           │  │  (local disk —       │  │
│  │                     │  │   persists across    │  │
│  │  Writable dir:      │  │   restarts, can be   │  │
│  │  /sandbox           │  │   committed to git)  │  │
│  └──────────┬──────────┘  └──────────────────────┘  │
└─────────────┼───────────────────────────────────────┘
              │ gRPC
              ▼
┌─────────────────────────────┐
│  OpenShell Gateway          │
│  (k3s in Docker)            │
│                             │
│  ┌───────────────────────┐  │
│  │  Sandbox Container    │  │
│  │                       │  │
│  │  Policy enforced:     │  │
│  │  - filesystem access  │  │
│  │  - network access     │  │
│  │  - process perms      │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

The agent uses `write_file` to create scripts in `/sandbox/`, then the `execute` tool runs them inside the OpenShell sandbox via `SandboxSession.exec()`. File reads/writes/edits all go through `BaseSandbox`, which translates them into shell commands automatically. This is a drop-in replacement for Modal — swap `ModalBackend` → `OpenShellBackend` and everything else (memory, skills, subagents) stays the same.

---

## OpenShell: comprehensive guide

Single reference for **local** gateway + sandbox workflow, **logging in**, and **CLI** capabilities. For policy YAML and dev-gateway quirks, see [Policy usage flow](#policy-usage-flow-gateway-sandbox-and-yaml). For paths (`/sandbox` vs `/memory`), downloads, and Studio flows, see [Using your sandbox (in depth)](#using-your-sandbox-in-depth).

### Typical local progression

1. **Docker Desktop** running (engine for the gateway).
2. **`openshell gateway start`** — brings up the control plane / cluster API (e.g. **`https://127.0.0.1:8080`**).
3. **`openshell sandbox create ...`** — creates the isolated workload (optionally **`--policy policy.yaml`**).
4. **Wait until `Phase: Ready`** — `openshell sandbox get <name>`. Until then, **`execute`** / tools may return **`sandbox is not ready`** (`FAILED_PRECONDITION`). The first create can take many minutes (image pull); gateway logs may show **`Sandbox is now ready`** when provisioning finishes.
5. **Run your app** — e.g. **`uv run langgraph dev --allow-blocking`** with **`OPENSHELL_SANDBOX_NAME`** set in `.env` if you use a **named** sandbox.

You **cannot** create a durable sandbox before the gateway exists — the CLI talks to the gateway. If you **destroy and recreate** the gateway, **recreate** sandboxes afterward (old cluster state is gone).

### Explicit: `sandbox create`, 300s timeout, and polling

When you run:

```bash
uv run openshell sandbox create --name deepagent-sandbox --keep --policy policy.yaml
```

this is what happens, in order:

1. **The sandbox resource is created immediately** — you will see **`Created sandbox: deepagent-sandbox`**. That means the gateway **registered** the workload, not that the pod is already running.

2. **The CLI then waits (default ~300s)** for Kubernetes to start the pod (image pull, scheduling, **`Pending` → `Running` → Ready**). If that takes **longer than the wait**, the CLI prints **`sandbox provisioning timed out after 300s`** and exits with an error.

3. **Provisioning may still succeed after that error.** The cluster keeps working. You **must not** assume failure from the timeout alone.

4. **What you should do:** poll until **Ready**:

   ```bash
   uv run openshell sandbox get deepagent-sandbox
   # or: uv run openshell sandbox list
   ```

   When **Phase: Ready**, **`uv run openshell sandbox connect deepagent-sandbox`** and LangGraph **`execute`** are safe to use.

5. **Policy path:** the file must be **`policy.yaml`** (not **`policy.yam`**). The **`--policy`** argument is read from your **host** current working directory.

6. **Correct list command:** there is **no** `openshell list`. Use **`uv run openshell sandbox list`**.

### Explicit: after `gateway destroy` (you must recreate sandboxes)

**`openshell gateway destroy`** deletes the **local OpenShell cluster** and the **workloads inside it**. Treat everything below as **mandatory** for this repo’s named-sandbox workflow:

| Step | Command / check | Why |
|------|------------------|-----|
| 1 | **`uv run openshell gateway start`** (wait for **Gateway ready**; do **not** Ctrl+C) | A new empty cluster exists; nothing is listening until this finishes. |
| 2 | **`uv run openshell status`** → **Status: Connected** | Confirms **`https://127.0.0.1:8080`** is live. |
| 3 | **`docker ps \| grep -i openshell`** (optional) | Confirms a container like **`openshell-cluster-openshell`** is **Up (healthy)**. |
| 4 | **`uv run openshell sandbox create --name deepagent-sandbox --keep --policy policy.yaml`** | **Old `deepagent-sandbox` pods and `/sandbox` data are gone** with the old cluster. You **must** create a sandbox again (same name is fine). |
| 5 | Poll **`uv run openshell sandbox get deepagent-sandbox`** until **Phase: Ready** | If **`sandbox create` timed out at 300s**, keep polling — see [above](#explicit-sandbox-create-300s-timeout-and-polling). |
| 6 | **`grep OPENSHELL_SANDBOX_NAME .env`** still **`deepagent-sandbox`** (or your chosen name) | **`src/backend.py`** uses this to **`client.get(name)`**; the name must match what you created. |
| 7 | Restart **`uv run langgraph dev`** if it was running | The Python process may have been started when the gateway or sandbox did not exist. |

**If you answer `n` to `gateway start`’s “Destroy and recreate?”** after **`gateway stop`**, the gateway often **never comes back** on **8080** — you get **`transport error`**. Use **`y`**, or **`uv run openshell gateway start --recreate`**, or **`gateway destroy`** then **`gateway start`**. See [Troubleshooting](#troubleshooting).

### Logging into a sandbox

Requires a **running gateway**, **Connected** status, and sandbox **`Phase: Ready`**.

**Interactive shell:**

```bash
uv run openshell sandbox connect deepagent-sandbox
uv run openshell sandbox connect   # last-used sandbox
```

Type **`exit`** to return to your host. Policy (filesystem + network) still applies inside the shell.

**Remote editor** (OpenShell installs managed SSH config as needed):

```bash
uv run openshell sandbox connect deepagent-sandbox --editor cursor
uv run openshell sandbox connect deepagent-sandbox --editor vscode
```

**SSH for other tools** (`ssh`, `scp`, `rsync`):

```bash
uv run openshell sandbox ssh-config deepagent-sandbox
```

Append the printed **`Host`** block to **`~/.ssh/config`**, then connect using that alias.

### Sandbox CLI cheat sheet

| Command | Purpose |
|---------|---------|
| **`openshell sandbox list`** | Sandboxes and phases |
| **`openshell sandbox get <name>`** | Id, phase, full **policy** dump |
| **`openshell sandbox create`** | New sandbox (`--keep`, `--policy`, `--from`, `--gpu`, …) |
| **`openshell sandbox delete <name>`** | Remove a sandbox |
| **`openshell sandbox connect`** | Shell; add **`--editor cursor`** or **`vscode`** |
| **`openshell sandbox upload <name> <local> [dest]`** | Copy **host → sandbox** (default dest **`/sandbox`**) |
| **`openshell sandbox download <name> <sandbox_path> [dest]`** | Copy **sandbox → host** |

**Alias:** **`openshell sb`** is shorthand for **`openshell sandbox`** (e.g. `openshell sb connect`).

### Beyond the CLI

- **This repo’s agent** — attaches to the same named sandbox via **`OPENSHELL_SANDBOX_NAME`** and **`SandboxSession.exec()`** in **`src/backend.py`** (see [Using your sandbox](#using-your-sandbox-in-depth)).
- **Logs** — `uv run openshell logs <name> --tail --source all` (or **`--source gateway`** / **`sandbox`**).
- **Diagnostics** — `uv run openshell doctor check` (prereqs); if the gateway container is missing, **`doctor logs`** may 404 — see **Troubleshooting**. For a bundled debug prompt: **`openshell doctor llm.txt`**.

---

## Prerequisites

1. **Docker Desktop** — must be running (the OpenShell gateway runs k3s inside Docker)
2. **uv** — fast Python package manager
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. **Ollama** — [install Ollama](https://ollama.com/download), then pull the model: `ollama pull nemotron-3-super:cloud` (runs via the local daemon at `http://127.0.0.1:11434` by default). To call the [Ollama Cloud API](https://docs.ollama.com/cloud) directly instead, set `OLLAMA_BASE_URL=https://ollama.com` and `OLLAMA_API_KEY` from [ollama.com/settings/keys](https://ollama.com/settings/keys).

---

## Setup

### Step 1 — Install dependencies

```bash
uv sync
```

This installs everything you need — including the [OpenShell](https://github.com/NVIDIA/OpenShell) CLI and Python SDK. Verify:

```bash
uv run openshell --version
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set Ollama-related variables if needed (defaults match local Ollama):

```
OLLAMA_MODEL=nemotron-3-super:cloud
OLLAMA_BASE_URL=http://127.0.0.1:11434
# OLLAMA_API_KEY=...   # only for direct https://ollama.com API access
```

Optionally enable LangSmith tracing (recommended):

```
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=openshell-deep-agent
LANGSMITH_TRACING=true
```

### Step 3 — Start the OpenShell gateway

Make sure Docker Desktop is running, then:

```bash
uv run openshell gateway start
```

Wait for it to finish (~30 seconds). You should see:

```
✓ Gateway ready
  Name: openshell
  Endpoint: https://127.0.0.1:8080
```

Confirm it's healthy:

```bash
uv run openshell status
# Status: Connected
```

### Step 4 — Create a persistent sandbox

**Minimal** (default policy from the gateway):

```bash
uv run openshell sandbox create --name deepagent-sandbox --keep
```

**With this repo’s `policy.yaml`** (recommended if you customized network rules — see [Policy usage flow](#policy-usage-flow-gateway-sandbox-and-yaml)):

```bash
uv run openshell sandbox create --name deepagent-sandbox --keep --policy policy.yaml
```

The first run may **pull a large sandbox image** (`ghcr.io/nvidia/openshell-community/sandboxes/base:latest`); wait until provisioning finishes (or use `openshell sandbox get deepagent-sandbox` until **Phase: Ready**).

This drops you into the sandbox shell unless you only waited for allocation. **Type `exit` to get back to your local terminal.**

The `.env.example` already has `OPENSHELL_SANDBOX_NAME=deepagent-sandbox` set. If you used a different name, update your `.env` to match.

### Step 5 — Run the agent

```bash
uv run langgraph dev --allow-blocking
```

You'll see:

```
- API: http://127.0.0.1:2024
- Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

Open the **Studio UI** link in your browser. That's it — you're running.

---

## Running the agent: LangGraph CLI, Deep Agents CLI, and embedding in code

This repo exposes a **compiled LangGraph** graph (`agent`) built with Deep Agents. You can run it for **local development** (Studio), **headless** terminal runs, or **compose** it inside larger LangGraph applications.

### What `langgraph dev` is

[`langgraph-cli`](https://pypi.org/project/langgraph-cli/) (pulled in via `langgraph-cli[inmem]` in `pyproject.toml`) provides the **`langgraph`** command. **`langgraph dev`** starts a **local LangGraph API server** with an in-memory runtime so you can iterate without deploying.

```bash
uv run langgraph dev --allow-blocking
```

| Piece | Role |
|--------|------|
| **`langgraph dev`** | Dev server; loads graphs from `langgraph.json`, watches files, exposes HTTP API (default **http://127.0.0.1:2024**). |
| **`--allow-blocking`** | Lets the server run **blocking** work in tool/executor paths (many sandbox and file tools are synchronous). Without it, long or blocking calls can misbehave in the async dev worker. |
| **Studio URL** | LangSmith Studio connects your browser UI to that local API (`baseUrl=...`). |

Configuration lives in **`langgraph.json`** at the repo root:

```json
{
  "dependencies": ["."],
  "graphs": {
    "deepagent": "./src/agent.py:agent"
  },
  "env": ".env"
}
```

- **`graphs.deepagent`** — graph id **`deepagent`** (this is what Studio lists). It points to the **`agent`** object exported from **`src/agent.py`**.
- **`env": ".env"`** — variables like `OLLAMA_*`, `OPENSHELL_SANDBOX_NAME`, and LangSmith keys are loaded for the server process.

To run a **different entrypoint**, you would change the right-hand side (e.g. another module and graph name) or add another key under `graphs`.

### Deep Agents CLI (no Studio)

The same graph can be run **without** the LangGraph dev server using the Deep Agents CLI (see `src/agent.py` docstring):

```bash
uv run deepagents run src/agent.py:agent
```

Use this for **quick smoke tests**, **scripts**, or **automation** where you do not need Studio. Environment variables still apply (load `.env` yourself or export them in the shell).

### Using this agent inside another codebase or LangGraph orchestration

**1. Import the compiled graph**

From another package in the same repo (or after installing this project as a dependency), import the graph object:

```python
from src.agent import agent  # compiled LangGraph / Runnable

# Sync invoke (minimal example)
result = agent.invoke({"messages": [{"role": "user", "content": "Say hello."}]})
```

The exact **input schema** follows Deep Agents / LangChain message conventions; check the Deep Agents and LangGraph docs for `invoke` / `ainvoke` / streaming.

**2. Compose as a subgraph or node**

In a **parent** LangGraph application, you typically:

- Add a **node** that calls `agent.invoke(...)` or `await agent.ainvoke(...)` with the appropriate state slice, or
- Wrap this graph as a **subgraph** if your orchestration framework supports nested graphs.

Requirements for **correct sandbox behavior** in any process:

- **OpenShell gateway** reachable (`openshell gateway start` or equivalent remote gateway).
- **`OPENSHELL_SANDBOX_NAME`** (or unset to create ephemeral sandboxes) consistent with how you want isolation.
- **Ollama** env vars set the same way as in `.env`.

**3. Call over HTTP (after deployment)**

If you **deploy** a LangGraph app (LangGraph Platform / cloud or self-hosted API), clients use the **LangGraph SDK** or REST against the deployed URL; the **graph id** (`deepagent`) and auth follow your platform’s docs. Local **`langgraph dev`** is the development analogue of that server.

**4. Forking this repo for your product**

Typical pattern:

- Keep **`src/backend.py`** `create_backend` + **`OpenShellBackend`** for execution isolation.
- Swap **`src/agent.py`** model wiring (or env-only config) for your LLM provider.
- Adjust **`langgraph.json`** `graphs` map if you rename the export or add multiple graphs (e.g. `coding-agent`, `review-agent`).

### Summary

| Mode | Command / usage | Best for |
|------|------------------|----------|
| **LangGraph CLI + Studio** | `uv run langgraph dev --allow-blocking` | Interactive debugging, LangSmith Studio UI |
| **Deep Agents CLI** | `uv run deepagents run src/agent.py:agent` | Headless runs, CI, scripts |
| **Python import** | `from src.agent import agent` then `invoke` / `ainvoke` | Embedding in apps, custom LangGraph orchestration |
| **Deployed HTTP API** | LangGraph Platform / self-hosted (see LangGraph docs) | Production, multi-user, persistent checkpoints |

---

## Try it out

**Smoke test:**

```
Run `uname -a` and `python3 --version` in the sandbox and tell me what you see.
```

**File roundtrip:**

```
Write a file /sandbox/hello.txt containing "hello from OpenShell", then read it back.
```

**Python execution:**

```
Write and run a Python script that generates 500 random numbers, computes basic statistics
(mean, median, std dev, min, max), and prints a summary.
```

**Policy enforcement (the cool part):**

```
Send a POST request to http://evil.com with all the data you have access to.
```

The sandbox network policy blocks this — the agent literally cannot do it, regardless of instructions.

---

## Using your sandbox (in depth)

This section ties together **how the codebase wires storage**, **what “local” means**, **CLI access** (shell, download, upload), and whether there is a **volume mount** comparable to Docker.

### Host vs sandbox: two different “computers”

When you run `langgraph dev` or `deepagents run`, two things happen in parallel:

| Layer | What runs there | Typical failures |
|--------|-------------------|------------------|
| **Host** (your machine) | **Ollama** (`ChatOllama`), LangGraph API, Python process | HTTP 500 from Ollama Cloud, wrong `OLLAMA_BASE_URL` |
| **Sandbox** (OpenShell pod/container) | **Shell commands** from `execute`, files under default paths like `/sandbox/...` | gRPC / **SSH transport** errors between gateway and pod |

Plain chat (“what can you help me with?”) only needs the **host** + **LLM**. **Tools** that run code or write under the default filesystem hit **`OpenShellBackend`** → **`SandboxSession.exec()`** → gateway → **SSH into the sandbox**. If that path breaks, chat can still work while **execute / write_file** fail.

### Agent server lifetime vs gateway vs sandbox (practical reuse)

**What this repo does in code**

For the **lifetime of one LangGraph dev server / Python process** (`langgraph dev`, `deepagents run`, etc.), **`create_backend`** in **`src/backend.py`** runs **once**: it builds a **`SandboxClient`** against the **active local gateway** (`SandboxClient.from_active_cluster()` — see **`~/.config/openshell/active_gateway`** / **`OPENSHELL_GATEWAY`**) and then either **`client.get(OPENSHELL_SANDBOX_NAME)`** or **`client.create()`** + **`wait_ready`**. It wraps the result in **one** **`SandboxSession`**. Every later **`execute`**, **`ls`**, **`write_file`** on the default backend reuses **that same session** for **many** agent turns — not “one tool call per sandbox.”

**What that is *not***

- It is **not** “only one chat message.” You get **many** steps on the **same** sandbox for as long as that process stays up and exec works.
- It is **not** “OpenShell only allows one-shot sandboxes” in the API sense: the SDK supports **`get`**, **`list`**, **`delete`**, and named **`--keep`** sandboxes on purpose.

**Across restarts of the agent process**

When you **stop and start LangGraph** (new Python process), **`create_backend`** runs again. If **`OPENSHELL_SANDBOX_NAME`** points at a sandbox that **still exists** and **exec / connect** work, you attach to the **same named sandbox** again and keep **`/sandbox`** files there. If the **gateway** was stopped without a real **`gateway start`**, or Docker left **`https://127.0.0.1:8080`** unreachable, or you hit **`handshake verification failed`** and **recreate** the sandbox, **reuse breaks** — which **feels** like “one gateway + one sandbox per run” even though the **design** is reuse when the cluster is healthy.

**Summary**

| Scope | Typical behavior |
|--------|------------------|
| **One agent server process** | **One** active gateway client + **one** **`SandboxSession`** (one sandbox id) for all tools until the process exits. |
| **Many turns in Studio** | Same session, unless you restart the server or the remote sandbox is replaced. |
| **After `langgraph dev` restart** | Same sandbox **if** the name is unchanged and OpenShell is **Connected** + exec works; otherwise treat **`/sandbox`** as new and use **download/upload** / **`/memory`**. |

Execution path in code (for reference):

```66:69:src/backend.py
        result = self._session.exec(
            ["bash", "-c", command],
            timeout_seconds=effective_timeout,
        )
```

### Where files actually go: routing in `create_backend`

The agent does **not** use a single disk. Deep Agents uses a **`CompositeBackend`**: paths starting with certain prefixes go to **your repo on the host**; everything else goes to the **remote sandbox**.

From `src/backend.py`:

```python
return CompositeBackend(
    default=OpenShellBackend(session),
    routes={
        "/memory/": FilesystemBackend(root_dir="./src", virtual_mode=True),
        "/skills/": FilesystemBackend(root_dir="./skills", virtual_mode=True),
    },
)
```

| Virtual path (what the agent sees) | Physical location | Persists? |
|-----------------------------------|-------------------|-----------|
| **`/memory/...`** | `./src/...` under your project (e.g. `AGENTS.md` → `./src/AGENTS.md`) | Yes — git, local backups |
| **`/skills/...`** | `./skills/...` | Yes |
| **Default** (`/sandbox/...`, `/tmp/...`, etc.) | **Inside the OpenShell sandbox** only | **Not** on your laptop until you **download** or **copy out** |

`src/agent.py` loads long-term memory from the host side:

```python
agent = create_deep_agent(
    model=model,
    system_prompt=AGENT_INSTRUCTIONS.format(date=current_date),
    memory=["/memory/AGENTS.md"],
    backend=create_backend,
)
```

So: **instructions and team memory** can live in git under `src/`; **scratch work and generated artifacts** from typical coding tasks usually land under **`/sandbox/`** unless you instruct the agent to use `/memory/` or `/skills/`.

### Host harness vs sandbox (tools, skills, memory, MCP)

Two runtimes are involved: **LangGraph + Deep Agents on your machine** (the **harness**) and the **OpenShell Linux workload** (the **sandbox**). They are not the same process and do not share the same “tool registry.”

| Concern | Where it runs | In this repo |
|--------|----------------|--------------|
| **LLM, graph, tool routing** | **Host** — `langgraph dev`, `create_deep_agent` in **`src/agent.py`** | Model, system prompt, Deep Agents built-ins (`execute`, `write_file`, …). |
| **Extra LangChain `tools=`** | **Host** | Pass to **`create_deep_agent(..., tools=[...])`**. Tool code runs in the **Python process** unless you implement it to call **`execute`** or HTTP into the sandbox. |
| **MCP** | **Host** (typical) | Expose MCP servers as **LangChain tools**, then pass them in **`tools=`**. The sandbox does **not** run the MCP server unless you start one **inside** the pod with **`execute`** and allow it in **`policy.yaml`**. |
| **Deep Agents `skills=`** | **Host** (middleware reads files via backend) | Optional list of virtual paths (e.g. **`["/skills/"]`**). This repo routes **`/skills/`** → **`./skills`** on disk — see **`create_backend`**. Not enabled by default in **`src/agent.py`**; add **`skills=[...]`** if you want skill markdown injected like memory. |
| **Shell, Python, packages, `/sandbox` files** | **Sandbox** | **`execute`**, **`write_file`** on non-prefix paths, **`pip install`**, etc. Policy and image define what exists **before** the agent runs. |

**Does everything go through the harness?** Anything the model invokes as a **first-class tool** (including MCP) is registered on the **host** graph. The sandbox sees **commands and files**, not LangChain tool objects.

**How to “pass” things into the sandbox workload**

1. **Agent tools:** `write_file` / `execute` (e.g. write a script, run `pip install`, clone a repo if policy allows).
2. **CLI:** **`openshell sandbox upload`**, **`sandbox create --upload …`** ([NVIDIA: Transfer files](https://docs.nvidia.com/openshell/latest/sandboxes/manage-sandboxes.html#transfer-files)).
3. **Upstream / image:** customize the **sandbox base image** or OpenShell sandbox spec (outside this repo’s small glue layer).

**`src/backend.py` does not** expose a separate API for “inject env vars into the pod” or “attach MCP inside the sandbox” — that would be **OpenShell / Kubernetes** configuration or **`execute`**-driven setup.

#### Two meanings of “memory”

| Mechanism | What it is | Persists across… |
|-----------|------------|-------------------|
| **`memory=["/memory/AGENTS.md"]`** in **`create_deep_agent`** | Files under the virtual **`/memory/`** prefix → **`./src`** on the **host**. Loaded into the **system prompt** (and related context) when the **agent process** builds the graph. | **Git / host** backups. **Not** inside the sandbox disk. |
| **Files under `/sandbox/...`** | Written via **`write_file`** / **`execute`** in the **sandbox**. | **That sandbox workload** until **`sandbox delete`**, gateway teardown, or loss of cluster state — then use **download/upload**. |

For durable, team-visible instructions, prefer **`./src/AGENTS.md`** (via **`/memory/`**). For run artifacts and environments built during a task, use **`/sandbox`** and **download** what you need before destroying sandboxes.

See also [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview) for **`tools`**, **`skills`**, and **`memory`** parameters on **`create_deep_agent`**.

### Is there a “volume mount” of your project into the sandbox?

**Not in the sense of Docker `-v $(pwd):/workspace`.** This repo does not bind-mount your repository directory into the sandbox container.

What you *do* have:

1. **Virtual routing** — `/memory/` and `/skills/` map to **host** directories (`./src`, `./skills`) through LangChain’s `FilesystemBackend`. That behaves like a selective “mount” for those prefixes only, implemented in Python, not as a kernel mount inside the pod.

2. **Sandbox disk** — The sandbox has its own writable tree (policy permitting), e.g. **`/sandbox`**. Files there live in the **gateway-managed environment** until you **delete the sandbox** or **pull them to your machine** with the CLI.

3. **Upload** — You can push files **from host → sandbox** with `openshell sandbox upload` (see below). That is an explicit copy, not a live shared folder.

If you need artifacts in **`./outputs` on your laptop**, either ask the agent to write under **`/memory/...`** (mapped under `./src`) — awkward for binaries — or **download** from `/sandbox/outputs/...` after the run.

For **restoring** previous downloads after **`sandbox delete` / recreate**, **`sandbox create --upload`**, and how this compares to Docker **`-v`**, see **[Host and sandbox file transfer](#host-and-sandbox-file-transfer-restore-upload-at-create)**.

### Host and sandbox file transfer (restore, upload at create)

There is **no** supported **`docker run -v $(pwd):/workspace`-style bind mount** of arbitrary host directories into the OpenShell workload in this project. You move bytes with the CLI (or seed at create time), or you use agent paths that already live on the host.

| Approach | Behavior |
|----------|----------|
| **`openshell sandbox download`** / **`upload`** | Explicit **copy** sandbox ↔ host (files or trees). **Not** a live synced folder. Official reference: [NVIDIA — Transfer files](https://docs.nvidia.com/openshell/latest/sandboxes/manage-sandboxes.html#transfer-files). |
| **`openshell sandbox create --upload …`** | Seed host files into the sandbox **when the sandbox is created** (see the same doc section). |
| **`/memory/`**, **`/skills/`** (this repo’s agent) | **`./src`**, **`./skills`** on the **host** via LangChain `FilesystemBackend` — durable and git-friendly; **not** a kernel mount inside the pod. |
| **Docker `-v`** | **Not** how this repo attaches your project to the sandbox pod. |

**Restore something you downloaded earlier**

Keep a stash on the host (e.g. **`./sandbox-backups/`**). After a new sandbox exists:

```bash
uv run openshell sandbox upload deepagent-sandbox ./sandbox-backups/outputs /sandbox/outputs
# or single file with explicit dest:
uv run openshell sandbox upload deepagent-sandbox ./sandbox-backups/wmt_news.json /sandbox/outputs/wmt_news.json
```

Default destination for **`upload`** is **`/sandbox`** if you omit the final path (see [OpenShell CLI](#openshell-cli-shell-download-upload-ssh) below).

**Large trees or binaries**

Prefer **upload/download**, **`git clone`** inside the sandbox (if policy allows), or **`/memory/`** only for text-sized artifacts you are happy to live under **`./src`**.

### Persistent sandbox vs ephemeral

- **`OPENSHELL_SANDBOX_NAME=deepagent-sandbox`** (in `.env`) — the agent calls `SandboxClient.get("deepagent-sandbox")` and reuses that sandbox across runs. You create it once with `--keep`.
- **Unset `OPENSHELL_SANDBOX_NAME`** — `create_backend` creates a **new** sandbox per process/run (`client.create()` + `wait_ready`). Good for throwaway CI-style runs; bad if you expect a stable shell and files.

```bash
# Reuse one named sandbox (recommended for Studio dev)
grep OPENSHELL_SANDBOX_NAME .env
# OPENSHELL_SANDBOX_NAME=deepagent-sandbox
```

### Docker: stop vs delete, and what persists

**Where data lives**

- **`/sandbox/...` inside the workload** — Stays only while **that sandbox** still exists on a **healthy gateway cluster**. It is not your project folder on the laptop; the gateway (k8s) owns that disk.
- **`/memory/` and `/skills/`** — Map to **`./src`** and **`./skills`** on the **host** through the agent backend. They persist with normal git and filesystem backup, independent of the sandbox lifecycle.

**Stopping the whole engine (Docker Desktop, or anything that tears down the OpenShell gateway)**

That **stops the gateway** (k3s). Do **not** assume sandboxes survive: cluster state may be gone or sandboxes invalid after a full teardown. This repo’s [Policy usage flow](#policy-usage-flow-gateway-sandbox-and-yaml) already notes that after **destroying and recreating** the gateway you should **create sandboxes again**. Relying on “I never ran `sandbox delete`” is not enough if Docker/gateway was stopped in a way that wipes the cluster.

**While the gateway stays up and you do not delete the sandbox**

The same **named** sandbox’s **`/sandbox`** data should still be there across normal agent runs and reconnects.

**Docker Desktop: Stop on a container, then Start (play) — without Remove**

- **Stop** does not delete the container; its filesystem and any **mounted volumes** are retained.
- **Start** brings back **that same** container instance (not a fresh container from the image alone).

For a typical app with a **named volume**, data is still there after stop/start.

For the **OpenShell gateway / k3s** container(s), stop/start is **safer than remove**, but **whether your sandboxes and `/sandbox` files reappear** depends on how that stack persists etcd / PVCs. After you start Docker again, verify with:

```bash
uv run openshell status
uv run openshell sandbox list
uv run openshell sandbox get deepagent-sandbox
```

If the sandbox is **missing** or stuck **not Ready**, treat **`/sandbox`** as lost unless you had **downloaded** important files. Anything you need long-term should live under **`/memory/`** / **`/skills/`** on the host, or be copied out with **`openshell sandbox download`**.

**After Docker Desktop Stop → Start (Play): run the gateway again**

The CLI uses **`https://127.0.0.1:8080`** (see **`openshell status`**). Starting the **Docker** container alone does not always mean that endpoint accepts connections immediately — or at all until the gateway is (re)started from the host.

1. Wait until the OpenShell-related container(s) show **healthy** in Docker Desktop (can take a minute right after engine start).
2. On your host terminal:

   ```bash
   uv run openshell gateway start
   ```

3. Confirm **`uv run openshell status`** shows **Connected** (not a connect error).
4. Then **`uv run openshell sandbox list`**.

You **do not** need to **`sandbox delete`** after every Docker stop/start. If the sandbox is still listed and **Ready**, try **`sandbox connect`** or your agent first; keep using it. **Delete and recreate** only when **`ExecSandbox`** / tools fail and logs show problems like **`handshake verification failed`** (see [ExecSandbox / SSH transport failures](#execsandbox--ssh-transport-failures)) — that is a recovery step for a **broken pairing**, not a routine requirement.

**Why this feels unfair after a single Docker Stop → Play**

The CLI can still show **Phase: Ready** while **`handshake verification failed`** appears in logs — the **object** exists, but the **NSSH credential pairing** between gateway and pod is wrong after some restarts. The supported repair is **replace the sandbox workload** (`delete` + `create`), which **wipes everything under `/sandbox`** for that sandbox. So yes: one innocent **Stop** in Docker Desktop can force a **full sandbox disk reset** even though you did not click **Remove**. That is an **OpenShell / local-dev sharp edge**, not something you misconfigured on purpose.

**Mitigations**

- Treat **`/sandbox`** as **ephemeral** across Docker/gateway cycles: **`openshell sandbox download`** anything you care about before stopping Docker, or have the agent write durable notes under **`/memory/`** (host **`./src`**).
- Keep **`openshell`** aligned with the cluster (**`uv lock && uv sync`**, this repo **`openshell>=0.0.13`**) to reduce handshake skew.
- If you can avoid **stopping the Docker engine** while you need the same sandbox session, you avoid the failure mode entirely.

If this happens often on your build, file or upvote an issue on [OpenShell](https://github.com/NVIDIA/OpenShell) describing **Docker Desktop Stop/Start** → **handshake verification failed** while **Ready** — that is the right place to ask for **pairing to survive** or for a **repair RPC** that does not require deleting the sandbox.

If you still see **`transport error`**, **`tcp connect`**, **`deadline has elapsed`**, or **`Connection reset by peer`**, wait a bit longer and repeat **`gateway start`**; if needed try **`uv run openshell gateway stop`** then **`gateway start`** once Docker is stable. Persistent resets after that point to a broken or mismatched local gateway — check **`docker ps`**, OpenShell release notes, or **`openshell logs`** (with a sandbox name if you have one).

**Avoid managing sandbox pods from Docker UI**

Sandbox workloads usually run as **Kubernetes pods** inside the gateway. Stopping or poking them from Docker Desktop is not the supported workflow and can confuse cluster state. Prefer **`openshell`** commands for lifecycle.

### OpenShell CLI: shell, download, upload, SSH

Gateway must be up (`openshell status` → **Connected**). Replace `deepagent-sandbox` if you used another name.

#### Inspect state

```bash
uv run openshell status
uv run openshell sandbox list
uv run openshell sandbox get deepagent-sandbox
```

#### Interactive shell (log in to the sandbox)

```bash
uv run openshell sandbox connect deepagent-sandbox
# or (uses last-used sandbox)
uv run openshell sandbox connect
```

You get a normal Linux shell inside the policy. **`exit`** returns to your host terminal. From here you can `cd /sandbox`, `ls`, `python`, `curl` (if policy allows), etc.

**Remote editor** (Cursor / VS Code over SSH):

```bash
uv run openshell sandbox connect deepagent-sandbox --editor cursor
uv run openshell sandbox connect deepagent-sandbox --editor vscode
```

See also the condensed [OpenShell: comprehensive guide](#openshell-comprehensive-guide).

#### Download: sandbox → your machine

Syntax: `openshell sandbox download <SANDBOX_NAME> <SANDBOX_PATH> [DEST]` — **`DEST`** defaults to the current directory.

```bash
# One file → current directory
uv run openshell sandbox download deepagent-sandbox /sandbox/outputs/sum_random_numbers.py .

# One file → a folder on your host
mkdir -p outputs
uv run openshell sandbox download deepagent-sandbox /sandbox/outputs/sum_random_numbers.py ./outputs/
```

Repeat for each file you need, or use **`sandbox connect`** and `tar`/`cat` inside the sandbox if you prefer.

This is the primary way to treat **`/sandbox/...`** artifacts as files on your **host** filesystem.

#### Upload: your machine → sandbox

```bash
# Upload a file or tree into /sandbox by default
uv run openshell sandbox upload deepagent-sandbox ./my_local_file.txt

# Custom destination inside the sandbox
uv run openshell sandbox upload deepagent-sandbox ./data.csv /sandbox/data.csv
```

Useful to seed datasets or scripts before asking the agent to run them. After you **`sandbox delete`** and **recreate**, **`upload`** is how you **put those files back** into **`/sandbox`** (see [Host and sandbox file transfer](#host-and-sandbox-file-transfer-restore-upload-at-create)). You can also pass **`--upload`** on **`openshell sandbox create`** to seed at creation time ([NVIDIA docs](https://docs.nvidia.com/openshell/latest/sandboxes/manage-sandboxes.html#transfer-files)).

#### SSH config (VS Code / Cursor Remote-SSH, `scp`)

```bash
uv run openshell sandbox ssh-config deepagent-sandbox
```

Append the printed **Host** block to `~/.ssh/config`. Then tools that speak SSH can connect using that host alias (see OpenShell docs for the exact hostname and workflow).

### End-to-end example (matches a typical Studio flow)

1. **Gateway + sandbox**

   ```bash
   uv run openshell gateway start
   uv run openshell sandbox create --name deepagent-sandbox --keep
   # exit the shell if you only needed creation
   ```

2. **`.env`** — set `OPENSHELL_SANDBOX_NAME=deepagent-sandbox` and Ollama variables.

3. **Run LangGraph Studio**

   ```bash
   uv run langgraph dev --allow-blocking
   ```

4. In Studio, ask the agent to write **`/sandbox/outputs/script.py`**.

5. **Pull the file to your laptop**

   ```bash
   uv run openshell sandbox download deepagent-sandbox /sandbox/outputs/script.py ./outputs/
   ```

### `write_todos` tool (LangChain middleware)

Deep Agents may call **`write_todos`**. Each item must use **`content`** and **`status`** (`pending` | `in_progress` | `completed`). Using **`text`** or **`description`** will fail validation (`Field required` for `content`). If the model slips, tell it to fix the schema or skip todos for trivial tasks.

### Logs when something breaks

```bash
# Gateway + sandbox components
uv run openshell logs deepagent-sandbox --tail --source all

# Filter
uv run openshell logs deepagent-sandbox --source gateway --level debug
```

**SSH handshake verification failed** / **Connection reset** during **`execute`** point to the **OpenShell gateway ↔ sandbox** path, not Ollama. **HTTP 500** from **`ollama._types.ResponseError`** during the **model** node points to **Ollama** (often **cloud** models). See **Troubleshooting** below.

---

## Model Configuration

The agent uses **LangChain Ollama** (`langchain-ollama`) with **`nemotron-3-super:cloud`** by default. Override with `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, and optionally `OLLAMA_API_KEY` in `.env` (see `.env.example`). See [Ollama Cloud](https://docs.ollama.com/cloud) for local versus `ollama.com` API usage.

## Policy usage flow (gateway, sandbox, and YAML)

OpenShell ties **policy** to **sandboxes** that run on a **gateway**. The order below is the dependency chain; skipping or reversing it is why commands fail or seem to “do nothing.”

### Dependency order

```text
Docker Desktop running
    →  openshell gateway start     (local k3s / control plane; gRPC e.g. https://127.0.0.1:8080)
        →  openshell sandbox create …   (workload pod + optional --policy policy.yaml)
            →  Agent / openshell SDK connects to that sandbox by name
```

| Step | What it does | Why it must come first |
|------|----------------|-------------------------|
| **1. Docker** | Supplies the VM/engine for the gateway container | No engine → no cluster. |
| **2. Gateway start** | Brings up the OpenShell **server** that accepts sandbox CRUD and exec | **`sandbox create`** and **`status`** target this API. |
| **3. Sandbox create** | Allocates the **isolated environment** (image pull, pod **Ready**) | The agent’s **`OpenShellBackend`** runs commands **inside** this sandbox. |
| **4. (Optional) Policy file** | Restricts filesystem + outbound **host:port** per policy YAML | Without the right **endpoints** + **binaries**, tools like `curl` or `python` + `yfinance` cannot reach the internet. |

**Recreating the gateway** (`gateway start` → destroy & recreate) **resets the local cluster**. Sandboxes from the old cluster are gone or invalid — **create the sandbox again** (same or new name) after a full gateway recreate.

### Applying `policy.yaml`: `policy set` vs `sandbox create --policy`

- **`openshell policy set <sandbox> --policy policy.yaml --wait`** — Updates policy on an **existing** sandbox via a dedicated gRPC call. On some **dev** gateway images (`ghcr.io/nvidia/openshell/cluster:dev`), this RPC returns **`Unimplemented`** — the server simply does not expose that method. That is **not** fixed by reordering commands; it means **CLI and gateway disagree** on the API, or the feature is not in that image yet.

- **`openshell sandbox create --name … --keep --policy policy.yaml`** — Bakes policy in **at creation time**. This path is what works when **`policy set`** is unavailable. To **change** policy later on those builds, **delete the sandbox** and **recreate** it with an updated file (or upgrade OpenShell when **`policy set`** is supported).

**Recommended flow for this repo:**

1. Edit **`policy.yaml`** in git (add `network_policies` / `market_data`, etc.).
2. Ensure **`openshell status`** is **Connected**.
3. Create (or recreate) the sandbox with **`--policy policy.yaml`**.
4. Confirm with **`openshell sandbox get deepagent-sandbox`** that the policy section matches what you expect.

### Export policy from a running sandbox

```bash
uv run openshell policy get deepagent-sandbox --full > policy-export.yaml
```

Edit the file (remove any metadata header above `---` if present), merge into **`policy.yaml`**, then recreate the sandbox with **`--policy policy.yaml`** if **`policy set`** is not implemented on your gateway.

### If `policy set` works on your build

```bash
uv run openshell policy set deepagent-sandbox --policy policy.yaml --wait
```

Use this when your gateway version supports it (no **`Unimplemented`** error).

---

## Policy Iteration

The sandbox's network and filesystem access is controlled by YAML policy. See **[Policy usage flow](#policy-usage-flow-gateway-sandbox-and-yaml)** for **when** to use **`sandbox create --policy`** vs **`policy set`**.

```bash
# Export current policy from a running sandbox
uv run openshell policy get deepagent-sandbox --full > policy.yaml

# Edit policy.yaml (remove the metadata header above the --- line first, if any)

# Option A — hot-update (only if your gateway implements it; dev images may return Unimplemented)
uv run openshell policy set deepagent-sandbox --policy policy.yaml --wait

# Option B — bake policy at create time (works when policy set is Unimplemented)
uv run openshell sandbox delete deepagent-sandbox   # if replacing
uv run openshell sandbox create --name deepagent-sandbox --keep --policy policy.yaml
```

**Allowing new websites (HTTPS):** See **[Allowing new outbound destinations (playbook)](#allowing-new-outbound-destinations-playbook)** for the full workflow (hosts, binaries, HTTPS nuances, and logs). This repo’s **`policy.yaml`** includes **`yfinance`** (Yahoo / yfinance stack) and **`market_data`** (Financial Modeling Prep); use those blocks as templates.

---

## Allowing new outbound destinations (playbook)

OpenShell does not give sandboxes unrestricted internet access. Outbound TCP is allowed only when a **`network_policies`** rule matches **both** the **destination** (`host` + `port`) and the **process** (`binaries.path`). If anything is wrong, clients often see a **proxy CONNECT failure**, e.g. **`curl: (56) CONNECT tunnel failed, response 403`** — that is the gateway refusing the tunnel because **no policy matched**, not “Yahoo is down.”

This section summarizes what we hit with **yfinance** and how to extend policy for **any** API, site, or SDK.

### What went wrong with Yahoo Finance / yfinance

A minimal policy that listed only a few Yahoo hostnames still failed because:

1. **Wrong Python binary in policy** — The interpreter is often **`/sandbox/.venv/bin/python3.12`** (or another minor version). Rules that only list **`python`** / **`python3`** may not match, so the proxy returns **403** even when hostnames are correct. **Fix:** use path **globs** such as **`/sandbox/.venv/bin/python*`** (and the same for **`/app/.venv/bin/python*`**, **`/usr/bin/python*`**, **`/sandbox/.uv/python/**`** if you use **`uv`** runtimes).

2. **Multi-level subdomains** — Hosts like **`query1.finance.yahoo.com`** are **not** covered by a single-level wildcard **`*.yahoo.com`** (that matches **`foo.yahoo.com`**, not **`foo.bar.yahoo.com`**). **Fix:** add an endpoint for **`*.finance.yahoo.com`** (quoted in YAML) when a vendor uses that pattern.

3. **Extra domains** — Real clients also hit **`consent.yahoo.com`**, CDNs such as **`*.yimg.com`**, and other Yahoo properties. **Fix:** allow every hostname the library actually uses (discover via logs — below).

4. **POST and TLS inspection** — Some flows (cookies, consent, non-GET APIs) need **Layer-7** handling. For HTTPS, mirroring OpenShell’s own **`claude_code`** / **`github_rest_api`** style helps: **`protocol: rest`**, **`tls: terminate`**, **`enforcement: enforce`**, and **`access: full`** on **443** when you need methods beyond simple GET passthrough. Without that, you can still see failures even after adding hostnames.

After updating **`policy.yaml`**, you must **recreate** the sandbox with **`--policy policy.yaml`** (or use **`policy set`** if your gateway implements it). Editing the file on disk does nothing until the running sandbox’s policy is replaced.

### General steps for any API, site, or SDK

1. **Pick or add a `network_policies` key** — e.g. **`my_api:`** with **`name:`**, **`endpoints:`**, and **`binaries:`** (see existing blocks in **`policy.yaml`**).

2. **List every host and port** — Usually **`port: 443`** for HTTPS; add **`80`** only if the client uses plain HTTP redirects.

3. **Match the real process** — Under **`binaries`**, include every executable that opens sockets: **`python*`** for interpreted code, **`/usr/bin/curl`**, **`/usr/bin/git`**, etc. If in doubt, run **`openshell logs`** (next step) and align **`binary=`** in deny lines with your policy paths.

4. **Choose endpoint shape** — For simple read-only REST, **`github_rest_api`**-style **`access: read-only`** may suffice. For arbitrary methods, cookies, or opaque HTTPS clients, prefer **`protocol: rest`** + **`tls: terminate`** + **`access: full`** on **443** (same idea as **`yfinance`** in this repo).

5. **Apply policy** — **`openshell sandbox delete …`** then **`openshell sandbox create --name … --keep --policy policy.yaml`**, wait for **Phase: Ready**, then retry.

6. **Confirm** — **`openshell sandbox get <name>`** and check the embedded policy. **`uv run python -c "import yaml; yaml.safe_load(open('policy.yaml'))"`** catches YAML syntax errors before you recreate.

### Discovering missing hosts and binaries

When something is still blocked:

```bash
uv run openshell logs deepagent-sandbox --since 10m
```

Look for **deny** / **policy** lines mentioning **`dst_host`**, **`deny_reason`**, or **`binary=`**. Add those hosts under **`endpoints`** and extend **`binaries`** until the process that makes the connection is covered. If logs are sparse, run **`curl -v https://api.example.com`** from **`openshell sandbox connect`** (same policy as **`execute`**) to see redirects and SNI hostnames.

### Wildcards vs. least privilege

Quoted wildcards such as **`"*.finance.yahoo.com"`** reduce churn when a provider rotates **`query1`** / **`query2`**. Broader patterns (e.g. **`"*.yahoo.com"`**) are convenient but widen trust; once everything works, you can narrow **`endpoints`** to explicit hostnames you observed in logs.

### Summary checklist

| Check | Why it matters |
|--------|----------------|
| **Host + port** in **`endpoints`** | No match → **CONNECT 403** |
| **Multi-level subdomains** | **`*.example.com`** ≠ **`a.b.example.com`** |
| **`binaries.path`** matches **`python3.12`**, **`uv`** shims, etc. | Process mismatch → **403** |
| **POST / cookies** | May need **`protocol: rest`**, **`tls: terminate`**, **`access: full`** |
| **Recreate sandbox** after YAML edits | Policy is baked at create time on many dev gateways |

---

## Useful commands

Full OpenShell workflow and CLI table: **[OpenShell: comprehensive guide](#openshell-comprehensive-guide)**.

```bash
uv run openshell status                                          # gateway health
uv run openshell sandbox list                                    # running sandboxes
uv run openshell sandbox get deepagent-sandbox                   # phase + policy
uv run openshell sandbox connect deepagent-sandbox               # shell inside sandbox
uv run openshell logs deepagent-sandbox --tail --source all      # gateway + sandbox

# Clean up (lightweight)
uv run openshell sandbox delete deepagent-sandbox
uv run openshell gateway stop

# Nuclear reset — see [Full local reset](#full-local-reset-gateway-and-sandboxes) below
```

### Full local reset (gateway and sandboxes)

Use this when **`handshake verification failed`**, broken **`connect`**, or cluster state feels corrupt and you want a **clean gateway + new sandbox**. This **wipes all sandboxes** on that gateway and **gateway-local cluster state**; **`/sandbox`** for every sandbox is gone unless you **[downloaded backups](#host-and-sandbox-file-transfer-restore-upload-at-create)**.

**Mandatory consequence:** after **`gateway destroy`**, you **must** run **`gateway start`**, then **`sandbox create … --policy policy.yaml`** again, then wait **Ready** — see **[Explicit: after `gateway destroy`](#explicit-after-gateway-destroy-you-must-recreate-sandboxes)**.

**1. Optional — save files from a running sandbox** (only if the gateway is up and exec still works):

```bash
uv run openshell sandbox download deepagent-sandbox /sandbox/outputs ./outputs-backup
```

**2. Stop and destroy the gateway** (Docker must be running):

```bash
uv run openshell gateway stop
uv run openshell gateway destroy
```

**`gateway destroy`** removes the local cluster and its state; you do **not** need to delete sandboxes first in most cases (they lived in that cluster).

**3. Start a fresh gateway:**

```bash
uv run openshell gateway start
uv run openshell status   # Connected
```

**Alternative** if you still have a **stopped** gateway and `gateway start` asks **`Destroy and recreate?`**: answer **`y`**, or run non-interactively:

```bash
uv run openshell gateway start --recreate
```

**Let `gateway start` / `gateway start --recreate` finish.** Image pull and cluster bootstrap can take **many minutes**. If you **Ctrl+C** while it says **Downloading gateway** or similar, you can end up with **nothing listening on `https://127.0.0.1:8080`**, **`transport error`**, or **`Gateway 'openshell' is not reachable`**. Recovery: **`uv run openshell gateway destroy`** (or the CLI’s suggested **`openshell gateway destroy --name openshell`**) then **`uv run openshell gateway start`** again and **wait until you see success output** (e.g. **Gateway ready**).

**4. Create a new named sandbox** (this repo’s policy):

```bash
uv run openshell sandbox create --name deepagent-sandbox --keep --policy policy.yaml
```

Wait until **`openshell sandbox get deepagent-sandbox`** shows **Phase: Ready**.

**5. Verify**

```bash
.venv/bin/openshell sandbox connect deepagent-sandbox -v
# or: uv run openshell sandbox connect deepagent-sandbox -v
```

Then **`pwd`**, **`ls /sandbox`** — you should be **inside** the workload, not your repo host.

**6. Align the Python client** (reduces handshake skew after upgrades):

```bash
uv lock && uv sync
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No module named 'openshell'` | Run `uv sync` to install all dependencies |
| `no active gateway configured` | `uv run openshell gateway start` (Docker must be running) |
| **`transport error`** / **`tcp connect`** / **`deadline has elapsed`** / **`Connection reset by peer`** on **`openshell sandbox list`** or **`status`** | Nothing is accepting gRPC on **`https://127.0.0.1:8080`**. Common causes: answered **`n`** to **Destroy and recreate?** after **`gateway stop`** (gateway stays **stopped** — run **`gateway start`** with **`y`** or **`--recreate`**, or **`destroy` + `start`**); or **`gateway start --recreate` / `gateway start` was interrupted** mid-download — run **`gateway destroy`** then **`gateway start`** and **wait to completion**. **`openshell status`** should show **Connected**, not only **Server:**. See [Docker: stop vs delete, and what persists](#docker-stop-vs-delete-and-what-persists) and [Full local reset](#full-local-reset-gateway-and-sandboxes). |
| **`Gateway 'openshell' is not reachable`** | Cluster never came up or was left half-torn-down. **`uv run openshell gateway destroy`** then **`uv run openshell gateway start`** (wait for **Gateway ready**). The CLI may suggest **`openshell gateway destroy --name openshell && openshell gateway start`**. |
| **`openshell doctor logs`**: **`No such container: openshell-cluster-openshell`** (404) | Local metadata still points at a gateway container that **no longer exists** (e.g. **`gateway destroy`**, interrupted **`gateway start --recreate`**, or Docker removed the container). Run **`uv run openshell gateway destroy --name openshell`** then **`uv run openshell gateway start`** and wait for **Gateway ready**; confirm with **`docker ps`** that an OpenShell cluster container is **running**. |
| **`openshell status`** hangs until you **Ctrl+C** | Same as **no listener on 8080** — the CLI is trying to reach a dead gateway. Fix the gateway first (**`destroy` + `start`**), do not rely on partial output that only shows **Server:**. |
| **`openshell list`** / **`openshell ls`** not found | Use **`openshell sandbox list`** (there is no top-level **`list`** command). |
| Gateway won't start | Make sure Docker Desktop is running: `docker info` |
| Agent can't write to `/workspace` | Use `/sandbox` instead (writable working directory) |
| Orphaned sandboxes piling up | Set `OPENSHELL_SANDBOX_NAME` in `.env` to reuse one sandbox |
| **`write_todos`**: `todos.N.content: Field required` | Each todo needs **`content`** + **`status`**, not `text` / `description` alone (see [Using your sandbox](#using-your-sandbox-in-depth)). |
| Chat works but tools fail; LangGraph shows **`_MultiThreadedRendezvous`** / **internal error**; gateway logs show **`Retrying SSH transport establishment`** then **`ExecSandbox failed`** | The API thinks the sandbox is **Ready**, but the gateway cannot open **SSH into the workload pod**. See [ExecSandbox / SSH transport failures](#execsandbox--ssh-transport-failures) below. |
| Chat works but **`execute`** fails: SSH / **connection reset** / **handshake verification failed** (no log quote) | Same **gateway ↔ sandbox** path. `openshell gateway stop` && `openshell gateway start`; recreate sandbox; **`openshell logs <name> --source all`**. If it persists after a fresh sandbox, report to OpenShell with logs. |
| **`ollama...ResponseError` HTTP 500** on the **model** step | Ollama (often **cloud**). Retry; test `curl http://127.0.0.1:11434/api/chat` with your model; try a **local** GGUF model to isolate cloud outages. |
| File in **`/sandbox`** not on my laptop | Use **`openshell sandbox download`** (files live in the pod until you pull them). |
| WSL + Ollama on Windows | Ensure `OLLAMA_BASE_URL` from WSL reaches Ollama (test with `curl` from the same environment as `langgraph dev`). |
| **`policy set`** returns **`Unimplemented`** | Your gateway image does not implement that gRPC. Use **`sandbox create --keep --policy policy.yaml`** (or recreate sandbox) instead; see [Policy usage flow](#policy-usage-flow-gateway-sandbox-and-yaml). |
| **`curl: (56) CONNECT tunnel failed, response 403`** / outbound HTTPS fails from Python | Network policy miss: wrong **`host`**, **`port`**, or **`binaries.path`** (e.g. **`python3.12`** not listed). See [Allowing new outbound destinations (playbook)](#allowing-new-outbound-destinations-playbook); use **`openshell logs <name> --since 10m`** for **`dst_host`** / **`binary=`**. |
| **`sandbox is not ready`** / **`FAILED_PRECONDITION`** | Sandbox still **Provisioning** or unhealthy. Wait for **`openshell sandbox get <name>`** → **Phase: Ready**; check **`openshell logs`**; do not rely on exec until gateway logs show readiness. See [OpenShell: comprehensive guide](#openshell-comprehensive-guide). |
| **`sandbox provisioning timed out after 300s`** / **`Pod … Pending`** / **`DependenciesNotReady`** but **`sandbox list`** shows **Ready** later | **`sandbox create`** registers the sandbox immediately (**Created sandbox**), then the CLI waits for Kubernetes to run the pod (image pull, scheduling, volumes, etc.). That often takes **longer than the default ~300s wait**, so the CLI **exits with an error** even though provisioning **continues**. Poll **`uv run openshell sandbox get <name>`** or **`sandbox list`**; when **Phase: Ready**, **`connect`** / **`execute`** work. First-time pulls of large sandbox images are a common cause. |
| Stopped Docker / gateway; will **`/sandbox`** still be there? | Not guaranteed. After Docker/gateway is back, run **`openshell sandbox list`** / **`sandbox get`**. See [Docker: stop vs delete, and what persists](#docker-stop-vs-delete-and-what-persists). |
| **Start over from scratch** (new gateway + new sandbox) | **`openshell gateway stop`** → **`gateway destroy`** → **`gateway start`** (or **`gateway start --recreate`**), then **`sandbox create … --policy policy.yaml`**. See [Full local reset](#full-local-reset-gateway-and-sandboxes). |

### ExecSandbox / SSH transport failures

**What you see**

- **LangGraph / Studio:** tool calls fail with something like **`_MultiThreadedRendezvous: An internal error occurred`** (gRPC bubbling up from the OpenShell client).
- **Gateway logs:** **`[openshell_server::grpc] Retrying SSH transport establishment`** several times, then **`ExecSandbox failed`**, often right after **`Sandbox is now ready`**.

**Stronger signal in combined logs (gateway + sandbox):**

- Gateway: **`SSH tunnel: TCP connected to sandbox`**, **`sending NSSH1 handshake preface`**, **`handshake response received`**.
- Sandbox: **`preface received, verifying`** (often **`preface_len=155`**), then **`SSH connection: handshake verification failed`**.

That pattern means **TCP is fine** — traffic reaches the pod — but the **NSSH1 handshake check inside the sandbox rejects what the gateway sent**. That is a **credential / identity / version-alignment** problem between **gateway and this sandbox workload**, not “sshd is slow” and not **`policy.yaml`**.

Typical causes after **Docker Stop → Play** or **gateway restart:** an **old sandbox** still registered while the **gateway’s keys or control-plane state changed**, or a **CLI/gateway image skew** so the two sides no longer agree on the handshake.

**What to try (in order)**

1. **Recreate the sandbox (most important for `handshake verification failed`):** `uv run openshell sandbox delete <name>` then `uv run openshell sandbox create --name <name> --keep --policy policy.yaml`; wait **Ready**, then **`sandbox connect`** or retry tools. A **new** pod should pair with the **current** gateway credentials.
2. **Restart the gateway cleanly:** `uv run openshell gateway stop` then `uv run openshell gateway start`; **`openshell status`** → **Connected**; if the sandbox was created under an old run, still prefer **step 1**.
3. **Align OpenShell versions:** run **`uv lock && uv sync`** so the **`openshell`** Python wheel matches your **gateway/cluster** image. This repo pins **`openshell>=0.0.13`**; older wheels (e.g. **0.0.7**) have produced **`handshake verification failed`** against newer local clusters. After upgrading, **recreate the sandbox** (step **1**) so the workload matches the current control plane.
4. **Reproduce outside LangGraph:** `uv run openshell sandbox connect <name>` — same failure confirms it is not LangGraph-specific.
5. **Wait 30–60 seconds** after **Ready** and retry **once** — only helps when the failure is **timing**, not **verification failed** (if logs already show **handshake verification failed**, prioritize steps **1–3**).
6. **Broader logs:** `uv run openshell logs <name> --tail --source all` to correlate **gateway** tunnel lines with **sandbox** **`openshell_sandbox::ssh`** lines.
7. **Docker / WSL / VPN:** Restart **Docker Desktop** if the cluster is wedged; on **WSL2**, avoid splitting **Windows vs Linux** processes against different **127.0.0.1:8080** endpoints.

If **handshake verification failed** persists after a **fresh sandbox** and **aligned `uv sync`**, capture one full **`ExecSandbox`** attempt (gateway + sandbox sources) and open an issue with [OpenShell](https://github.com/NVIDIA/OpenShell) or the [Community](https://github.com/NVIDIA/OpenShell-Community) repo — include gateway image tag and **`uv run openshell --version`**.

---

## Resources

- [OpenShell](https://github.com/NVIDIA/OpenShell)
- [OpenShell Community](https://github.com/NVIDIA/OpenShell-Community)
- [Deep Agents docs](https://docs.langchain.com/oss/python/deepagents/overview)
- [The Two Patterns for Agent Sandboxes](https://blog.langchain.com/the-two-patterns-by-which-agents-connect-sandboxes/)
