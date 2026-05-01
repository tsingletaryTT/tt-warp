# Getting Started with tt-warp

tt-warp wires your Tenstorrent hardware into Warp as a first-class development environment. The agent knows your devices, can switch environments, dispatch workloads, and diagnose crashes — all running locally on your silicon, no cloud calls.

---

## Install

```bash
cd ~/code/tt-warp
pip install -e .
tt-warp install
tt-warp sync
```

`install` does three things:
- Registers `tt-hardware` in `~/.warp/.mcp.json` so any agent in Warp can call TT tools
- Installs the shell hook (`~/.tt-warp/tt-warprc`) for your prompt chip
- Copies the six skill files to `~/.warp/skills/`

`sync` fetches the offline knowledge corpus (~43 lessons from tt-vscode-toolkit).

**Add the shell hook to your shell** (if it wasn't added automatically):

```bash
echo 'source ~/.tt-warp/tt-warprc' >> ~/.bashrc
source ~/.bashrc
```

---

## Your prompt chip

After sourcing the hook, your prompt gains a status line above the cursor:

```
⬡P300C  metal  ●llama3  68°C
❯ _
```

| Piece | Meaning |
|-------|---------|
| `⬡P300C` | Board type from tt-smi (teal = healthy, yellow = warm, red = error) |
| `metal` | Active TT environment (pink) |
| `●llama3` | Local LLM endpoint alive on :8000 (green) |
| `68°C` | Chip temperature — shown only above 70°C threshold |

The chip reads `~/.tt-warp/state.json`. If the file is under 30 seconds old it reads it directly (no blocking subprocess). If stale, it refreshes in the background and shows the previous reading for this prompt cycle.

---

## What the agent can do

Open a Warp agent session and ask it anything TT-related. The agent calls MCP tools automatically — you don't need to invoke them directly.

| Ask the agent | What it calls |
|---------------|---------------|
| "What hardware do I have?" | `tt_list_devices()`, `tt_status()` |
| "Which environment do I need for forge?" | `tt_activate_env("forge")` |
| "Generate a video of a cat surfing" | `tt_serve()`, `tt_generate()` |
| "Why did my kernel crash?" (paste log) | `tt_diagnose()`, `tt_knowledge()` |
| "Run my script on the P300C" | `tt_run_workload()` |
| "How do I set up hugepages?" | `tt_knowledge("hugepages")` |
| "Is my system healthy?" | `tt_doctor()` |

---

## Environments

Four TT environments are registered. The agent switches between them via `tt_activate_env(name)`:

| Name | Venv path | Use for |
|------|-----------|---------|
| `metal` | `~/tt-metal/python_env` | tt-metal kernels, TTNN ops |
| `vllm` | `~/tt-metal/build/python_env_vllm` | vLLM inference (Llama, Mistral) |
| `forge` | `~/tt-forge-venv` | PyTorch model compilation via Forge |
| `xla` | `~/tt-xla-venv` | JAX / XLA workloads |

**Important:** `forge` must unset `TT_METAL_HOME` — the agent handles this automatically via `tt_activate_env("forge")`.

To switch manually (without the agent):
```bash
# Ask the agent for the snippet, or call directly:
tt-mcp-server  # then in another tab ask: "give me the activation snippet for forge"
```

Or just tell the agent: *"switch to the forge environment"* — it returns the snippet and you eval it.

---

## Workload dispatch

When you ask the agent to run something, it tries these in order:

1. **tt-ctl** (if installed) — best UX, full service lifecycle
2. **tt-inference-server Docker image** (if cached) — `docker run` with correct `--device` flags
3. **Direct tt-metal / tt-forge** — activate env, run script
4. **Guided setup** — walks you through installation via the `tt-setup` skill

---

## Beer handoff

When the hardware is occupied loading a model, the agent routes to a CPU Qwen3-0.6B sidecar on `:8001` so it stays responsive. When the hardware LLM comes back up on `:8000`, it transitions back automatically. You can see the current routing state in `tt_status()`:

```json
{
  "llm": {
    "active_url": "http://localhost:8001",
    "hardware_busy": true,
    "primary_url": "http://localhost:8000",
    "fallback_url": "http://localhost:8001"
  }
}
```

---

## Diagnosing crashes

Paste your error output into the agent and say *"diagnose this"*. The agent calls `tt_diagnose()` which pattern-matches against known TT error signatures:

| Category | Common cause | Quick fix |
|----------|-------------|-----------|
| `hugepages` | Huge pages not configured | `sudo sysctl -w vm.nr_hugepages=<N>` (agent gets N from knowledge) |
| `shm` | Stale shared memory from killed process | Clear `/dev/shm/tenstorrent*`, run `tt-smi -r` |
| `wrong_venv` | Wrong Python environment active | Switch with `tt_activate_env()` |
| `noc_timeout` | Hardware/driver state | Reset devices via `tt_reset_devices()` |
| `driver_mismatch` | Firmware/driver version mismatch | Update via tt-installer |

---

## Knowledge sync

The offline corpus (~43 lessons from [tt-vscode-toolkit](https://github.com/tenstorrent/tt-vscode-toolkit)) lives at `~/.tt-warp/knowledge/knowledge.db`. Refresh it:

```bash
tt-warp sync              # lessons only (default)
tt-warp sync --source all # lessons + tenstorrent.github.io
```

The corpus is filtered by your detected hardware — queries for P300C workloads won't return N150-only lessons. The agent calls `tt_knowledge(query)` automatically; you can also ask it directly: *"what lessons exist for generating video on Blackhole?"*

---

## tt-lang kernel development

If you're writing custom kernels with tt-lang, tell the agent you're in a kernel development context. It applies the `ttlang-workflow` skill: simulate first with `ttlang-sim`, compile via the Docker `dist` image, run on hardware — and calls `tt_diagnose()` on any crash before suggesting fixes.

---

## First-time setup (no runtime installed)

If `tt_doctor()` shows missing components, the agent walks you through installation incrementally using the `tt-setup` skill. It won't overwhelm you with all steps at once — it fixes one missing piece, re-checks with `tt_doctor()`, then moves to the next.

---

## Files installed

| Path | Purpose |
|------|---------|
| `~/.warp/.mcp.json` | Registers `tt-hardware` MCP server |
| `~/.tt-warp/tt-warprc` | Shell hook (source from .bashrc) |
| `~/.tt-warp/state.json` | Hardware state cache (written by MCP server + shell) |
| `~/.tt-warp/knowledge/knowledge.db` | Offline knowledge corpus |
| `~/.warp/skills/tt-*.md` | Agent behavioral guides |

---

## Troubleshooting

**Prompt chip not showing:**
```bash
source ~/.tt-warp/tt-warprc
echo $PROMPT_COMMAND   # should contain _tt_update_prompt
```

**MCP server not appearing in Warp:**
```bash
cat ~/.warp/.mcp.json   # verify tt-hardware entry
tt-mcp-server           # should start without error
```

**Agent says "no hardware detected":**
```bash
tt-smi -s   # verify tt-smi works and returns device_info
```

**Re-run install:**
```bash
tt-warp install   # safe to run multiple times, overwrites in place
```
