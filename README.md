# tt-warp

A [Warp](https://www.warp.dev/) plugin that makes Tenstorrent hardware a first-class terminal development environment. The agent knows your devices, switches environments, dispatches workloads, and diagnoses crashes — all running locally on your silicon. Nothing phones home.

---

## Prerequisites

### Warp terminal

tt-warp is a Warp plugin. You need Warp installed and running. Linux only — same constraint as TT hardware.

**Debian / Ubuntu:**
```bash
sudo apt-get install wget gpg
wget -qO- https://releases.warp.dev/linux/keys/warp.asc | gpg --dearmor > warpdotdev.gpg
sudo install -D -o root -g root -m 644 warpdotdev.gpg /etc/apt/keyrings/warpdotdev.gpg
sudo sh -c 'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/warpdotdev.gpg] https://releases.warp.dev/linux/deb stable main" > /etc/apt/sources.list.d/warpdotdev.list'
rm warpdotdev.gpg
sudo apt update && sudo apt install warp-terminal
```

**Fedora / RHEL / CentOS:**
```bash
sudo rpm --import https://releases.warp.dev/linux/keys/warp.asc
sudo sh -c 'echo -e "[warpdotdev]\nname=warpdotdev\nbaseurl=https://releases.warp.dev/linux/rpm/stable\nenabled=1\ngpgcheck=1\ngpgkey=https://releases.warp.dev/linux/keys/warp.asc" > /etc/yum.repos.d/warpdotdev.repo'
sudo dnf install warp-terminal
```

**Arch Linux:**
```bash
sudo pacman -U ./<file>.pkg.tar.zst
```
Download the `.pkg.tar.zst` from [warp.dev/download](https://www.warp.dev/download) first.

Warp requires glibc >= 2.31 and OpenGL ES 3.0+ or Vulkan.

**First launch requires a Warp account.** Sign up is free at [warp.dev](https://www.warp.dev). After signing in, make sure **AI features are enabled** in Settings — the MCP server and skills only activate inside a Warp agent session.

**Building from source** (Warp went open source May 7, 2026, under AGPL-3.0; the `warpui_core`/`warpui` crates are dual-licensed MIT):
```bash
git clone https://github.com/warpdotdev/warp
cd warp
./script/bootstrap   # installs build and runtime deps
./script/run         # builds and runs the `warp` binary
```
The cargo bin target is `warp` (not a separate `warp-oss` binary). A source build still uses the same `~/.warp` config directory as the packaged release. Whether it requires a Warp account at first launch is not fully documented — the FAQ notes some features run fully locally while cloud features (Drive, hosted agents, the agent's LLM calls) require Warp's backend.

### Tenstorrent hardware

A supported TT card must be physically installed:

| Board | Architecture | Notes |
|-------|-------------|-------|
| N150 | Wormhole | Single chip |
| N300 | Wormhole | Dual chip |
| T3K | Wormhole | 4× N300 boards in a ring |
| P300C | Blackhole | Dual chip |
| P150X4 | Blackhole | 4× P300C boards |

tt-warp works without hardware (it will report "no devices detected") but most tools are inert without a card.

### tt-smi

The TT system management interface. If it isn't installed, tt-warp's hardware tools won't function.

```bash
tt-smi --version
```

If missing, install via [tt-installer](https://github.com/tenstorrent/tt-installer):

```bash
curl -s https://raw.githubusercontent.com/tenstorrent/tt-installer/main/install.sh | bash
```

Restart your shell after installing.

### Python 3.11+

```bash
python3 --version   # must be 3.11 or newer
```

### Optional but recommended

- **Docker** — enables the tt-inference-server dispatch path (Docker images for Wan2.2, Llama3, etc.)
- **tt-ctl** — if installed, gets priority over Docker for service lifecycle management
- **tmux** — tt-warp extends the tmux status bar with hardware state when detected

---

## Install

### From PyPI (recommended)

```bash
pip install tt-warp
tt-warp install
tt-warp sync
```

### From source

```bash
git clone https://github.com/tsingletaryTT/tt-warp ~/code/tt-warp
cd ~/code/tt-warp
pip install -e .
tt-warp install
tt-warp sync
```

> Development currently lives at `tsingletaryTT/tt-warp`; it will move to the `tenstorrent` org later.

Use the from-source path if you want to contribute, modify behavior, or run unreleased changes. `pip install -e .` installs in editable mode so edits to the source take effect immediately without reinstalling.

---

`tt-warp install` does three things:
- Registers `tt-hardware` in `~/.warp/.mcp.json` so any Warp agent session can call TT tools
- Writes the shell hook to `~/.tt-warp/tt-warprc`
- Copies the eight skill files to `~/.warp/skills/`

`tt-warp sync` fetches the offline knowledge corpus from [tt-vscode-toolkit](https://github.com/tenstorrent/tt-vscode-toolkit) (~43 validated lessons, ~50 MB).

**Wire the shell hook into your shell:**

```bash
echo 'source ~/.tt-warp/tt-warprc' >> ~/.bashrc
source ~/.bashrc
```

For zsh, use `~/.zshrc` instead.

---

## Verify the install

```bash
# Hardware detected?
tt-smi -s | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['device_info']), 'device(s)')"

# MCP server registered?
cat ~/.warp/.mcp.json

# Skills installed?
ls ~/.warp/skills/

# Knowledge corpus present?
ls ~/.tt-warp/knowledge/

# Shell hook active?
echo $PROMPT_COMMAND   # should contain _tt_update_prompt
```

---

## Prompt chip

After sourcing the hook, a hardware status line appears above your prompt:

```
⬡P300C  forge  ●llama3  71°C
❯ _
```

| Piece | Meaning |
|-------|---------|
| `⬡P300C` | Board type from tt-smi; teal = healthy, yellow = warm/busy, red = error |
| `forge` | Active TT environment |
| `●llama3` | Local LLM endpoint alive on `:8000`; absent when none found |
| `71°C` | Chip temperature; shown only above the 70°C threshold |

The chip reads `~/.tt-warp/state.json`. If the file is under 30 seconds old it reads directly (sub-millisecond). If stale it refreshes in the background, so there is no blocking subprocess on the critical path.

When inside tmux, the same information is written to the tmux status bar.

---

## AI agent options

tt-warp registers the TT hardware MCP server with both **Warp** and **Claude Code**. Use whichever AI you have open.

### Warp agent (Ctrl+I)

Warp's agent routes LLM calls through Warp's servers — a free Warp account is required. The MCP tools (`tt-mcp-server`) and skills run entirely locally; only the completions go over the network.

Open a Warp agent session (Ctrl+I or the agent icon) and describe what you want to do. The agent calls MCP tools and applies skills automatically.

### Claude Code

`tt-warp install` registers `tt-hardware` with Claude Code's global MCP config (user scope). In any `claude` session the TT tools are immediately available — no Warp account required, LLM calls go to Anthropic directly.

```
claude                       # start Claude Code
# then ask: "what TT hardware do I have?"
```

| Say this | Agent does |
|----------|-----------|
| "What hardware do I have?" | `tt_list_devices()` + `tt_status()` |
| "Switch to the forge environment" | `tt_activate_env("forge")` |
| "Generate a video of a sunset over mountains" | `tt_serve()` → `tt_generate()` |
| "Why did my workload crash?" (paste the log) | `tt_diagnose()` + `tt_knowledge()` |
| "Serve Qwen3-32B" / "run a model" | `tt_serve("Qwen3-32B")` (sizes the device automatically) |
| "What's the best model to run on my box?" | tt-serve-llm skill → model zoo + chip sizing |
| "Open a chat window for my model" | tt-connect-ui skill (Open WebUI → `:8000/v1`) |
| "Run my script on all devices" | `tt_run_workload(script, devices)` |
| "Is my system ready to run workloads?" | `tt_doctor()` |
| "Show me the logs for the llama3 service" | `tt_logs("llama3")` |
| "How do I configure hugepages for my hardware?" | `tt_knowledge("hugepages")` |

---

## Environments

Four TT framework environments are registered. The agent selects and activates the right one automatically.

| Name | Venv path | Use for |
|------|-----------|---------|
| `metal` | `~/tt-metal/python_env` | tt-metal kernels, TTNN ops, custom operators |
| `vllm` | `~/.tenstorrent-venv` (QB2) or `~/tt-metal/build/python_env_vllm` | vLLM inference (Llama, Mistral, Qwen) |
| `forge` | `~/tt-forge-venv` | PyTorch model compilation via tt-forge |
| `xla` | `~/tt-xla-venv` | JAX workloads via tt-xla |

`forge` requires unsetting `TT_METAL_HOME` — the agent handles this when it calls `tt_activate_env("forge")`. Never mix envs in one shell session without deactivating first.

On Blackhole hardware (e.g. a QB2), `tt_activate_env` also exports `TT_METAL_ARCH_NAME=blackhole` for the `metal`/`vllm` envs — tt-metal needs it to select the right device backend. The arch is auto-detected from the connected board, and the `vllm` env resolves to `~/.tenstorrent-venv` when present (a QB2 ships vLLM there and has no tt-metal source tree, so `TT_METAL_HOME` is left unset).

---

## Workload dispatch

When you ask the agent to run a workload, it tries these in order and stops at the first that works:

1. **tt-ctl** (if `tt-ctl` is on PATH) — best UX, full service lifecycle management
2. **tt-inference-server `run.py`** (pre-installed on a QB2 at `~/.local/lib/tt-inference-server/`) — for model-serve requests; sizes `--tt-device` to the model (`p100` for ≤14B, `p300x2` for 70B/32B-class) and exposes the OpenAI-compatible API on `:8000`
3. **tt-inference-server Docker image** (if image is cached) — `docker run` with the device, 1G-hugepages mount, and `HF_TOKEN`; polls `:8000` for readiness
4. **Direct execution** — activates the correct env and runs the script
5. **Guided setup** — if nothing is installed, the `tt-setup` skill walks you through it step by step

---

## Beer handoff

Loading a large model occupies the TT hardware for 30–120 seconds. During that window, the agent routes to a CPU Qwen3-0.6B sidecar on `:8011` so it stays responsive and can answer questions while the hardware loads. When the hardware LLM comes back on `:8000`, it transitions back automatically.

> The sidecar uses `:8011`, not `:8001` — on a QB2 (and any tt-inference-server host) `:8001` is the inference server's own prompt server, so binding it would collide.

You can see the current state via the agent ("what's the LLM routing state?") or by reading `~/.tt-warp/state.json`:

```json
{
  "llm": {
    "active_url": "http://localhost:8011",
    "hardware_busy": true,
    "primary_url": "http://localhost:8000",
    "fallback_url": "http://localhost:8011"
  }
}
```

---

## Diagnosing crashes

Paste your error output into the agent and say *"diagnose this"*. The agent passes the log to `tt_diagnose()` which matches known TT error patterns:

| Category | Common cause | Typical fix |
|----------|-------------|-------------|
| `hugepages` | Huge pages not configured | `sudo sysctl -w vm.nr_hugepages=<N>` — ask agent for N |
| `shm` | Stale shared memory from killed process | Clear `/dev/shm/tenstorrent*`, run `tt-smi -r` |
| `wrong_venv` | Wrong Python environment | Switch env via `tt_activate_env()` |
| `noc_timeout` | Hardware/driver state corruption | Reset via `tt_reset_devices()` |
| `driver_mismatch` | Firmware/driver version skew | Update firmware via tt-installer |

---

## Knowledge corpus

The offline corpus lives at `~/.tt-warp/knowledge/knowledge.db` (SQLite). It's filtered by your detected hardware — if you have a P300C, Wormhole-only lessons are excluded from results.

```bash
tt-warp sync                  # sync lessons from tt-vscode-toolkit (default)
tt-warp sync --source all     # also crawl tenstorrent.github.io
tt-warp sync --embed          # re-embed on TT hardware for semantic search (Phase 2)
```

The agent queries the corpus automatically via `tt_knowledge()`. You can also ask directly: *"what lessons are there for running vLLM on T3K?"*

---

## tt-lang kernel development

Working on custom TT-Metal kernels with tt-lang? Tell the agent and it applies the `ttlang-workflow` skill:

1. **Simulate** with `ttlang-sim` — catches logic errors without touching hardware
2. **Compile** via the `tt-lang-dist` Docker image
3. **Run** on hardware with the correct env active
4. **Debug** — `tt_diagnose()` on any crash before attempting fixes

---

## No runtime installed?

If `tt_doctor()` reports missing components, say *"help me get set up"* and the agent walks through installation one step at a time: tt-smi → hugepages → Docker image → framework env. It re-checks after each step and only proceeds when the previous piece is confirmed working.

---

## Files installed

| Path | What it is |
|------|-----------|
| `~/.warp/.mcp.json` | Registers the `tt-hardware` MCP server with Warp |
| `~/.tt-warp/tt-warprc` | Shell hook — source from `.bashrc` / `.zshrc` |
| `~/.tt-warp/state.json` | Hardware state cache (written by MCP server and shell) |
| `~/.tt-warp/knowledge/knowledge.db` | Offline knowledge corpus |
| `~/.warp/skills/tt-*.md` | Agent behavioral guides (eight skills) |

---

## Troubleshooting

**Prompt chip not showing**
```bash
source ~/.tt-warp/tt-warprc
echo $PROMPT_COMMAND   # must contain _tt_update_prompt
```

**MCP server not appearing in Warp agent**
```bash
cat ~/.warp/.mcp.json   # verify tt-hardware entry exists
tt-mcp-server           # should start without traceback
```

**Agent says "no hardware detected"**
```bash
tt-smi -s   # must return JSON with device_info array
```

**Something changed and tools are broken**
```bash
tt-warp install   # safe to re-run; overwrites in place
tt-warp sync      # re-fetch corpus
```

---

## Architecture

```
④ tt-knowledge  (offline corpus, hardware-filtered)
① tt-mcp-server (self-contained MCP tool surface)
② tt-warp-shell (PROMPT_COMMAND chip + tmux bar)
③ TT Skills     (eight behavioral guides for the agent)
         ↕
TT Hardware  (tt-smi, tt-metal runtime, Docker)
```

Each layer is independent and ships separately, and each targets a documented Warp agent-platform surface: the MCP server registers via `~/.warp/.mcp.json` ([MCP docs](https://docs.warp.dev/agent-platform/capabilities/mcp/)), the skills install as `~/.warp/skills/<name>/SKILL.md` ([Skills docs](https://docs.warp.dev/agent-platform/capabilities/skills/)), and the shell chip rides the standard `PROMPT_COMMAND` hook. Because Warp shares the cross-tool Agent Skills format, the same skill files also load under Claude Code, Codex, and other agents.
