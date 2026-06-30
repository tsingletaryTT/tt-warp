# WARP.md — project rules for tt-warp

Project rules for [Warp](https://docs.warp.dev/agent-platform/capabilities/rules/)
agents (and any agent reading this file) working in the tt-warp repository.

## What this project is

tt-warp is a **Warp plugin** that makes Tenstorrent (TT) hardware a first-class
terminal environment. It has four independent layers, each shipping separately:

| Layer | Code | Installs to |
|-------|------|-------------|
| MCP server (the tool surface) | `tt_mcp/` | `~/.warp/.mcp.json` as `tt-hardware` |
| Skills (agent behavioral guides) | `skills/` | `~/.warp/skills/<name>/SKILL.md` |
| Shell chip (prompt + tmux status) | `shell/tt-warprc` | sourced from `~/.tt-warp/tt-warprc` |
| Knowledge corpus (offline lessons) | `tt_mcp/knowledge/` | `~/.tt-warp/knowledge/knowledge.db` |

The `tt-warp` CLI (`tt_warp/cli.py`) wires all of this in via `tt-warp install`
and fetches the corpus via `tt-warp sync`.

## Conventions (always follow)

- **Bump the version on any behavioral change.** Edit `version` in
  `pyproject.toml` (currently `0.1.x`). Do this in the same commit as the change.
- **Write well-commented code.** Explain *why*, not just *what*. Revise stale
  comments and docs to match reality rather than leaving them wrong.
- **Keep the README accurate.** It is the primary user-facing doc; when behavior
  changes, update it in the same change. Don't let it drift back into describing
  Warp integration as speculative — Warp's agent platform is shipped and
  documented.
- **`tt-smi -s`** — always use snapshot/JSON mode when reading hardware state,
  never the interactive TUI.

## Skill authoring (these are real footguns — verify before committing)

- **Frontmatter must be the very first thing in the file.** Line 1 is `---`.
  Do NOT put a comment, blank line, or anything before it — a leading line stops
  Warp/Claude Code from parsing the frontmatter, so the skill loses its `name`
  and `description` and never auto-triggers.
- Every `SKILL.md` requires two frontmatter fields: `name` (kebab-case) and
  `description` (when to use it — phrased as a trigger, e.g. "Use when…").
- Skills live as flat `*.md` files in `skills/`; the installer copies each to
  `~/.warp/skills/<stem>/SKILL.md`. Keep one skill per file.
- Skills describe *workflows* the agent invokes; they should call the `tt_*`
  MCP tools rather than reimplementing logic.

## MCP tools

The server exposes 11 tools (`tt_mcp/server.py`), all prefixed `tt_`:
`tt_status`, `tt_list_devices`, `tt_activate_env`, `tt_run_workload`,
`tt_generate`, `tt_serve`, `tt_diagnose`, `tt_doctor`, `tt_logs`,
`tt_reset_devices`, `tt_knowledge`. When adding a tool, register it in the
README usage table and reference it from the relevant skill.

## QB2 / Blackhole target (the primary deployment)

tt-warp's first-class target is a QuietBox 2: **2× Blackhole p300c cards = 4
chips = 4 independent PCIe devices** (not a mesh; no inter-chip Ethernet). Facts
the code and skills depend on — keep them true:

- **vLLM venv is `~/.tenstorrent-venv`**, not the tt-metal build tree. A QB2 has
  no tt-metal source (`~/tt-metal` holds venvs only), so do NOT point
  `TT_METAL_HOME` at it for the QB2 vLLM env. `envs.py` resolves this.
- **`TT_METAL_ARCH_NAME=blackhole`** is required for metal-backed envs;
  `tt_activate_env` auto-detects and exports it.
- **Serving** goes through the pre-installed `tt-inference-server` launcher at
  `~/.local/lib/tt-inference-server/run.py`. Device sizing: `p100` = one chip
  (≤14B models), `p300x2` = all four (70B/32B-class). `dispatch._tt_device_for`
  encodes this; the ~70B ceiling is real (bigger needs an 8-chip box).
- **Qwen3-32B ships pre-cached** on a QB2 — the best zero-download default model.
- **Port map:** `:8000` = inference server (OpenAI API), `:8001` = its prompt
  server, `:3000` = tt-studio. The CPU sidecar therefore binds **`:8011`**, never
  `:8001` — changing that reintroduces a collision.

## Testing

- Run the suite with `python -m pytest`. **Note:** this venv ships a broken
  `pytest_asyncio` plugin that aborts collection on import; run
  `python -m pytest -p no:asyncio` to get a green run. The asyncio plugin is not
  needed by these tests.
- All install/sync/dispatch logic is unit-tested under `tests/`; add coverage for
  new CLI behavior and new MCP tools.

## Config locations are not negotiable

Warp reads agent config from a single `~/.warp` directory across every channel
(stable `warp-terminal`, the open-source `warp` build, preview). Do not invent
suffixed dirs like `.warp-oss` or `.warp-dev` — they are undocumented and Warp
never reads them. The installer writes only to `~/.warp`.

## Machine-wide TT rules (for users, not this repo)

A `WARP.md` only applies when an agent works inside *this* repo. To make any
Warp agent session on a TT machine prefer the `tt_*` tools and respect TT
constraints (e.g. "never mix framework envs in one shell"), add those as
**Global Rules** in Warp Drive → Personal → Rules. Warp does not expose a
file path for global rules, so the installer cannot place them automatically.
