# OpenShell CLI — simple guide

Run via the project venv (`uv run openshell …` or an activated `.venv`). Docker Desktop must be running for a local gateway.

```bash
openshell <command> --help   # details for any command
```

---

## Mental model

| Layer | What it is |
|-------|------------|
| **Gateway** | Local control plane (k3s in Docker). CLI talks to it over gRPC (often `https://127.0.0.1:8080`). |
| **Sandbox** | Isolated Linux workload where code runs, under a **policy**. |
| **Policy** | YAML allowlist for filesystem + outbound network (not prompt text). |

Typical order: **gateway start → sandbox create → connect / agent use**.

---

## Everyday workflow

```bash
# 1. Control plane
openshell gateway start
openshell status                          # expect Status: Connected

# 2. Sandbox (this repo: keep + policy)
openshell sandbox create --name michael-shell --keep --policy policy.yaml
openshell sandbox get michael-shell       # wait until Phase: Ready
# If create times out at ~300s, provisioning may still finish — keep polling get/list

# 3. Use it
openshell sandbox connect michael-shell   # interactive shell
# Point the agent at the same name: OPENSHELL_SANDBOX_NAME=michael-shell in .env
```

Set `OPENSHELL_SANDBOX_NAME` to a sandbox that **exists**; otherwise LangGraph fails with `sandbox not found`.

---

## Where scripts live / download to local

Agent-written files under **`/sandbox/...`** exist **only inside the sandbox** (not in your git tree). Host paths `/memory/` and `/skills/` in this app map to `./src` and `./skills` on the laptop.

```bash
# Download sandbox → host
openshell sandbox download michael-shell /sandbox/myscript.py .
openshell sandbox download michael-shell /sandbox/myscript.py ./outputs/

# Upload host → sandbox
openshell sandbox upload michael-shell ./local.py /sandbox/local.py

# Browse interactively
openshell sandbox connect michael-shell   # then: ls /sandbox
```

Full path table: [openshell-deep-agents.md — Where agent scripts live](openshell-deep-agents.md#where-agent-scripts-live-and-how-to-download).

---

## Command map

### Gateway

| Command | Purpose |
|---------|---------|
| `gateway start` | Deploy/start local gateway (default name `openshell`, port `8080`) |
| `gateway start --recreate` | Destroy and recreate from scratch |
| `gateway stop` | Stop (preserves state) |
| `gateway destroy` | Tear down gateway **and** its state (sandboxes go away) |
| `gateway select <name>` | Choose active gateway |
| `gateway info` | Deployment details |
| `gateway add` / `login` | Point at / auth to an existing or edge gateway |
| `status` | Connected? endpoint? version? |

Aliases: `openshell gw …`

### Sandbox

| Command | Purpose |
|---------|---------|
| `sandbox create` | Create workload; optional `--name`, `--policy`, `--from`, `--gpu`, `--upload`, `--editor` |
| `sandbox list` | Names + phases |
| `sandbox get <name>` | Id, phase, embedded policy |
| `sandbox delete <name>` | Remove sandbox |
| `sandbox connect [name]` | Shell (or `--editor cursor` / `vscode`) |
| `sandbox upload <name> <local> [dest]` | Host → sandbox (default dest `/sandbox`) |
| `sandbox download <name> <path> [dest]` | Sandbox → host |
| `sandbox ssh-config <name>` | Print SSH `Host` block for Remote-SSH / scp |

Aliases: `openshell sb …`

**Useful `create` flags**

- `--keep` — don’t delete when the first shell exits (default-ish durable use)
- `--no-keep` — ephemeral; delete after exit
- `--policy policy.yaml` — bake FS/network policy at create
- `--from <name\|Dockerfile\|image>` — image source
- `--upload <local>[:<sandbox-path>]` — seed files at create
- `--forward <port>` — port-forward during create
- `--gpu` — request GPU

After `Created sandbox: …`, the CLI waits for Ready (~300s). Timeout ≠ dead; poll `get` / `list`.

### Policy

| Command | Purpose |
|---------|---------|
| `policy get <name>` | Show active policy (`--full` for YAML) |
| `policy set <name> --policy policy.yaml [--wait]` | Hot-update (may be `Unimplemented` on some gateway images) |
| `policy list <name>` | Revision history |
| `policy set --global --policy …` | Gateway-wide lock for all sandboxes |
| `policy delete --global` | Remove global lock |

If `policy set` fails, **delete + recreate** with `--policy policy.yaml`. Editing the file on disk alone does nothing.

Aliases: `openshell pol …`

### Logs & diagnostics

| Command | Purpose |
|---------|---------|
| `logs [name]` | Sandbox/gateway logs (`-n`, `--tail`, `--since 10m`, `--source gateway\|sandbox\|all`, `--level debug`) |
| `doctor check` | Prerequisites |
| `doctor logs` | Gateway container logs |
| `doctor exec -- <cmd>` | Run inside gateway container (e.g. `kubectl get pods -A`) |
| `doctor llm.txt` | Long diagnostic prompt for agents |

Aliases: `openshell lg …`, `openshell dr …`

### Port forwarding

| Command | Purpose |
|---------|---------|
| `forward start <port> [sandbox]` | Local port → sandbox |
| `forward stop <port>` | Stop forward |
| `forward list` | Active forwards |

Aliases: `openshell fwd …`

### Settings, providers, inference

| Command | Purpose |
|---------|---------|
| `settings get/set/delete` | Sandbox or `--global` settings (e.g. `log_level`) |
| `provider create/list/get/update/delete` | Credentials for tools inside sandboxes (OpenAI, Anthropic, …) |
| `inference get/set/update` | Gateway-level default model/provider |

### Extras

| Command | Purpose |
|---------|---------|
| `term` | Interactive TUI |
| `completions <bash\|zsh\|fish\|powershell>` | Shell completions |
| `ssh-proxy` | Used by SSH `ProxyCommand` (usually not run by hand) |

### Global flags / env

| Flag / env | Purpose |
|------------|---------|
| `-g` / `OPENSHELL_GATEWAY` | Gateway name |
| `--gateway-endpoint` / `OPENSHELL_GATEWAY_ENDPOINT` | Direct URL |
| `-v` / `-vv` / `-vvv` | Verbosity |
| `OPENSHELL_SANDBOX_NAME` | Used by **this repo’s agent**, not by every CLI command |
| `OPENSHELL_SANDBOX_POLICY` | Default policy path for create when `--policy` omitted |

---

## Cheat sheet (copy/paste)

```bash
openshell gateway start
openshell status
openshell sandbox create --name my-sandbox --keep --policy policy.yaml
openshell sandbox list
openshell sandbox get my-sandbox
openshell sandbox connect my-sandbox
openshell sandbox connect my-sandbox --editor cursor
openshell sandbox upload my-sandbox ./data.csv /sandbox/data.csv
openshell sandbox download my-sandbox /sandbox/out.txt ./outputs/
openshell policy get my-sandbox --full
openshell policy set my-sandbox --policy policy.yaml --wait   # if supported
openshell logs my-sandbox --since 10m --source all
openshell forward start 8080 my-sandbox
openshell doctor check
openshell sandbox delete my-sandbox
openshell gateway stop
# full wipe:
openshell gateway destroy && openshell gateway start
```

---

## This repo tips

1. Prefer **`create --keep --policy policy.yaml`** so FS/network rules match git.
2. Match **`.env` → `OPENSHELL_SANDBOX_NAME`** to a **Ready** sandbox name.
3. After **`gateway destroy`**, create the sandbox again (old pods are gone).
4. Network denials often look like `CONNECT … 403` — check `logs` for `dst_host` / `binary=` / `deny_reason`, then update policy and recreate.
5. Scripts under **`/sandbox`** are **not** on your laptop — use **`sandbox download`** (see [Where scripts live](#where-scripts-live--download-to-local)).

For deeper repo context (timeouts, policy playbook, agent wiring), see:

- [Reuse in another project](reusing-in-another-project.md) — files / imports / deps to copy
- [OpenShell policy tutorial](openshell-policy-tutorial.md) — **set and update policy**
- [OpenShell + Deep Agents — components & ways to run](openshell-deep-agents.md)
- Root [README](../README.md)
