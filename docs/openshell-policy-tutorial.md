# Tutorial: set and update OpenShell policy

This is the definitive how-to for **`policy.yaml`** in this repo. Goal: make it obvious **where** policy lives, **how** to apply it, and **how** to change it without guessing.

Policy is **not** controlled by LangGraph, Deep Agents prompts, or editing a file and hoping the running sandbox notices. Policy is attached to the **sandbox** (or optionally locked gateway-wide).

---

## 60-second truth

| Fact | Detail |
|------|--------|
| **Source of truth on disk** | Project file **`policy.yaml`** (repo root) |
| **What enforces it** | OpenShell sandbox / gateway (FS Landlock + egress proxy) |
| **How to apply first time** | `openshell sandbox create … --policy policy.yaml` |
| **How to update (reliable)** | Edit YAML → **delete** sandbox → **create** again with `--policy policy.yaml` |
| **How to update (if supported)** | `openshell policy set <name> --policy policy.yaml --wait` |
| **How to verify** | `openshell policy get <name> --full` or `openshell sandbox get <name>` |
| **What does nothing** | Only editing `policy.yaml` while the old sandbox keeps running |

```text
policy.yaml  ──create --policy──►  sandbox (enforced)
     ▲                                    │
     │         policy get --full          │
     └──────── export / inspect ◄─────────┘

Edit file ──► must policy set OR delete+create ──► live rules change
```

---

## Prerequisites

```bash
# From repo root, venv on
docker info                                 # Docker Desktop up
uv run openshell gateway start              # once; wait for Gateway ready
uv run openshell status                     # Status: Connected
```

Use your real sandbox name everywhere below (examples use `michael-shell`). It should match `OPENSHELL_SANDBOX_NAME` in `.env` if you run the agent.

---

## Part 1 — Understand what you’re setting

Open `policy.yaml`. The important sections:

### 1. Filesystem

```yaml
filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    # ...
  read_write:
    - /sandbox
    - /tmp
    - /workspace
```

- Agent code should write under **`/sandbox`** (this repo’s convention).
- Paths not listed are denied for that access mode.

### 2. Process / Landlock

```yaml
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox
```

### 3. Network (most common edits)

Each block under `network_policies` is an allow-bundle. **Both** must match or the proxy returns **403**:

1. **Destination** — `host` + `port` (usually `443`)
2. **Binary** — which executable opens the socket (`binaries.path`)

Example shape:

```yaml
network_policies:
  my_api:
    name: my-api
    endpoints:
      - host: api.example.com
        port: 443
        protocol: rest
        tls: terminate
        enforcement: enforce
        access: full          # or read-only
    binaries:
      - path: /sandbox/.venv/bin/python*
      - path: /usr/bin/curl
```

**Binary gotcha:** `/usr/bin/python3` does **not** match `/sandbox/.venv/bin/python3.12`. Prefer globs like `python*`.

**Host gotcha:** `*.yahoo.com` does **not** match `query1.finance.yahoo.com`. You may need `*.finance.yahoo.com`.

---

## Part 2 — Set policy for the first time (create)

**Always pass `--policy` when you care about this repo’s rules.** Omit it and you get a default / built-in policy — not necessarily your git file.

```bash
cd /path/to/openshell-deepagent

# Optional: sanity-check YAML
uv run python -c "import yaml; yaml.safe_load(open('policy.yaml')); print('OK')"

uv run openshell sandbox create \
  --name michael-shell \
  --keep \
  --policy policy.yaml
```

Notes:

- **`--keep`** — keep the sandbox after the first shell exits (what you want for agent use).
- **`--policy policy.yaml`** — path is relative to your **current working directory** on the host.
- Create may print **`Created sandbox`** then wait ~300s. Timeout does **not** always mean failure — poll Ready:

```bash
uv run openshell sandbox get michael-shell
# expect Phase: Ready
```

If the name already exists:

```text
UNIQUE constraint failed: objects.object_type, objects.name
```

→ either use that sandbox (`get` / `list`) or `delete` then create again (see Part 3).

### Confirm policy was applied

```bash
uv run openshell policy get michael-shell --full
# or:
uv run openshell sandbox get michael-shell
```

You should see your `filesystem_policy` and `network_policies` blocks, not an unrelated default.

Also fine:

```bash
uv run openshell sandbox connect michael-shell
# inside sandbox, try something allowed / denied to spot-check
```

---

## Part 3 — Update policy (change rules on an existing sandbox)

You edited `policy.yaml`. Now make the **running** sandbox match it.

### Method A — Hot update (`policy set`) — try this first

```bash
uv run openshell policy set michael-shell --policy policy.yaml --wait
uv run openshell policy get michael-shell --full   # confirm
```

- **`--wait`** — block until the sandbox loads the new policy (default timeout 60s; raise with `--timeout 120` if needed).
- If this succeeds, you’re done. **No delete.** `/sandbox` files stay.

#### If you see `Unimplemented`

Some gateway images do not implement the `policy set` RPC. That is a **gateway limitation**, not a bad YAML file. Use **Method B**.

### Method B — Delete and recreate (always works)

**Warning:** deleting the sandbox removes its workload and **`/sandbox` data**. Download anything you need first.

```bash
# Optional backup
uv run openshell sandbox download michael-shell /sandbox/important.py ./backup/

uv run openshell sandbox delete michael-shell

uv run openshell sandbox create \
  --name michael-shell \
  --keep \
  --policy policy.yaml

# Wait until Ready
uv run openshell sandbox get michael-shell
uv run openshell policy get michael-shell --full
```

If LangGraph / your agent is running, **restart it** after recreate so `create_backend` re-attaches cleanly.

Restore files if needed:

```bash
uv run openshell sandbox upload michael-shell ./backup/important.py /sandbox/important.py
```

### Which method should I use?

| Situation | Use |
|-----------|-----|
| `policy set … --wait` works | **Method A** |
| `Unimplemented` / set fails / unsure | **Method B** |
| Major FS layout change | Prefer **B** |
| Need to wipe sandbox state anyway | **B** |

**Recommended default for this repo:** edit → try **A** → if it fails, **B**.

---

## Part 4 — Export / inspect / history

```bash
# Full YAML from the live sandbox (compare to git policy.yaml)
uv run openshell policy get michael-shell --full

# Save export (strip any metadata header above --- if present before merging)
uv run openshell policy get michael-shell --full > policy-export.yaml

# Revision history
uv run openshell policy list michael-shell

# A specific revision (if you use list numbers)
uv run openshell policy get michael-shell --rev 1 --full
```

Diff mental model: **git `policy.yaml`** is what you *intend*; **`policy get --full`** is what the sandbox *actually has*. They diverge until you set or recreate.

---

## Part 5 — Gateway-global policy (optional, advanced)

You can lock policy for **all** sandboxes on the gateway:

```bash
uv run openshell policy set --global --policy policy.yaml --yes
uv run openshell policy get --global --full
```

Remove the global lock (sandboxes use their own policy again):

```bash
uv run openshell policy delete --global
```

Use sparingly for local single-sandbox workflows. Prefer per-sandbox `--policy` / `policy set <name>`.

Env fallback at **create** time (if you omit `--policy`):

```bash
export OPENSHELL_SANDBOX_POLICY=/path/to/policy.yaml
```

`--policy` on the CLI overrides that.

---

## Part 6 — Workflow: allow a new HTTPS API

Concrete loop when the agent or sandbox gets **`CONNECT … 403`**:

```bash
# 1. See what was denied
uv run openshell logs michael-shell --since 10m --source all
# Look for: dst_host, binary=, deny_reason

# 2. Edit policy.yaml
#    - add network_policies.<name>.endpoints host/port
#    - add binaries.path matching the deny line (use globs)
#    - for POST/cookies/REST: protocol: rest, tls: terminate, access: full

# 3. Validate YAML
uv run python -c "import yaml; yaml.safe_load(open('policy.yaml')); print('OK')"

# 4. Apply (A or B from Part 3)
uv run openshell policy set michael-shell --policy policy.yaml --wait \
  || (uv run openshell sandbox delete michael-shell && \
      uv run openshell sandbox create --name michael-shell --keep --policy policy.yaml)

# 5. Verify + retry the call
uv run openshell policy get michael-shell --full | head -80
```

This repo’s `yfinance` and `market_data` blocks in `policy.yaml` are good templates.

---

## Part 7 — Copy-paste cheat sheet

```bash
SANDBOX=michael-shell   # change me
POLICY=policy.yaml

# --- first set ---
uv run openshell sandbox create --name "$SANDBOX" --keep --policy "$POLICY"
uv run openshell sandbox get "$SANDBOX"              # Phase: Ready
uv run openshell policy get "$SANDBOX" --full

# --- update (hot) ---
uv run openshell policy set "$SANDBOX" --policy "$POLICY" --wait
uv run openshell policy get "$SANDBOX" --full

# --- update (recreate) ---
uv run openshell sandbox delete "$SANDBOX"
uv run openshell sandbox create --name "$SANDBOX" --keep --policy "$POLICY"
uv run openshell sandbox get "$SANDBOX"
uv run openshell policy get "$SANDBOX" --full

# --- debug ---
uv run openshell logs "$SANDBOX" --since 10m --source all
```

---

## Common mistakes

| Mistake | Result | Fix |
|---------|--------|-----|
| Create without `--policy` | Default policy, not your file | Recreate with `--policy policy.yaml` |
| Edit YAML only | Live sandbox unchanged | `policy set` or delete+create |
| Wrong cwd when passing `policy.yaml` | File not found / wrong file | Run from repo root or pass absolute path |
| Name typo vs `.env` | Agent: `sandbox not found` | Align `OPENSHELL_SANDBOX_NAME` |
| Host allowed, binary wrong | `403` CONNECT | Fix `binaries.path` / globs |
| Assume `policy set` always works | `Unimplemented` | Use delete+create |
| Recreate without download | Lost `/sandbox` files | `sandbox download` first |

---

## Relation to the agent

- **`src/backend.py`** never loads `policy.yaml`. It only attaches to a named/existing sandbox.
- LangGraph / `invoke` / Studio inherit whatever policy that sandbox already has.
- After recreate, restart `langgraph dev` (or your process) so the session reconnects.

---

## Related docs

- [OpenShell CLI guide](openshell-cli.md) — full CLI map
- [Components & ways to run](openshell-deep-agents.md) — stack / run modes
- [README — Policy usage flow](../README.md#policy-usage-flow-gateway-sandbox-and-yaml)
- [README — Allowing new outbound destinations](../README.md#allowing-new-outbound-destinations-playbook)
