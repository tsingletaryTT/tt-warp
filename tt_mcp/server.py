"""
tt-mcp-server — FastMCP server exposing TT hardware as agent tools.

This module is the main entry point for the MCP server that allows AI agents
to interact with Tenstorrent hardware through a standardised set of tools.

Entry point: tt-mcp-server (registered in pyproject.toml scripts).

Tools provided (11 total):
    tt_status         — snapshot of device state, env, and LLM routing
    tt_list_devices   — enumerate all attached TT devices with metadata
    tt_activate_env   — return activation snippet for a TT Python env
    tt_run_workload   — run a Python script on TT hardware
    tt_generate       — submit a generation job (video/image/text)
    tt_serve          — start a local inference server for a model
    tt_diagnose       — parse a TT error log into structured diagnoses
    tt_doctor         — full system health check
    tt_logs           — tail logs for a running TT service
    tt_reset_devices  — reset all TT devices via tt-smi -r
    tt_knowledge      — search the local TT knowledge corpus

Architecture notes:
    - Lazy singletons (_llm_state, _db) are created on first use to keep
      startup fast and avoid blocking on I/O during import.
    - _refresh_state() merges hardware, env, and LLM routing into one dict
      and persists it to STATE_PATH so external tools can also read it.
    - All tools return plain dicts (JSON-serialisable) so callers don't need
      to know about internal dataclasses.
"""
from __future__ import annotations

import json
import shutil as _shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

from tt_mcp import hardware, envs, diag, dispatch
from tt_mcp.llm import probe_endpoints, LLMState
from tt_mcp.cpu_sidecar import CpuSidecar
from tt_mcp.knowledge.db import KnowledgeDB

# ---------------------------------------------------------------------------
# Server instantiation
# ---------------------------------------------------------------------------

# The server name appears in MCP handshake metadata and log output.
mcp = FastMCP("tt-hardware")

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# Persistent state file written after every status refresh.
# External processes (CLI, shell prompt chip) can read this to avoid
# re-running tt-smi on every invocation.
STATE_PATH = Path("~/.tt-warp/state.json").expanduser()

# SQLite knowledge corpus built by `tt-warp sync`.
DB_PATH = Path("~/.tt-warp/knowledge/knowledge.db").expanduser()

# ---------------------------------------------------------------------------
# Lazy singletons — created on first use, never re-created within a session
# ---------------------------------------------------------------------------

# Cached result of the last LLM endpoint probe.  A None here means we haven't
# probed yet; we probe lazily so server startup doesn't block on network I/O.
_llm_state: Optional[LLMState] = None

# CpuSidecar instance for the running Qwen3 sidecar process (if any).
# Not currently exposed directly via tools, but kept here so future tools
# can reference it without re-discovering the PID.
_sidecar: Optional[CpuSidecar] = None

# Open handle to the SQLite knowledge corpus.  None if the corpus hasn't been
# synced yet (DB_PATH doesn't exist) or if it failed to open.
_db: Optional[KnowledgeDB] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_llm_state() -> LLMState:
    """Return a cached LLM state, probing endpoints on first call.

    The probe is intentionally deferred so the MCP handshake completes
    quickly even if the local LLM endpoints are unreachable.
    """
    global _llm_state
    if _llm_state is None:
        _llm_state = probe_endpoints()
    return _llm_state


def _get_db() -> Optional[KnowledgeDB]:
    """Return an open KnowledgeDB handle, or None if the corpus is absent.

    The corpus is created by `tt-warp sync` and may not exist on a fresh
    install.  Tools that use this should handle None gracefully.
    """
    global _db
    if _db is None and DB_PATH.exists():
        _db = KnowledgeDB(DB_PATH)
    return _db


def _refresh_state(extra: Optional[dict] = None) -> dict:
    """Write a fresh hardware+env+LLM snapshot to STATE_PATH and return it.

    Merges:
      - hardware.write_state() output (device list, mesh, timestamp, …)
      - current active Python environment name
      - LLM routing state (active_url, occupied flag, etc.)

    The merged dict is persisted as pretty-printed JSON so that the shell
    prompt chip and CLI can read it without re-running tt-smi.

    Args:
        extra: Optional additional keys to embed in the state dict before
               writing.  Forwarded as-is to hardware.write_state().

    Returns:
        The full merged state dict.
    """
    # hardware.write_state() does the tt-smi call and initial JSON write;
    # we augment it with env and LLM data and overwrite the file.
    state = hardware.write_state(STATE_PATH, extra)
    state["env"] = envs.detect_active_env()
    state["llm"] = _get_llm_state().to_dict()
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------

@mcp.tool()
def tt_status() -> dict:
    """Return device list, health, active env, and LLM routing state.

    This is the primary "what's going on?" query.  It runs tt-smi, detects
    the active Python environment, probes LLM endpoints, and returns a
    single merged dict.  The result is also persisted to ~/.tt-warp/state.json
    so other processes can read a recent snapshot without re-invoking.

    Returns a dict with keys: devices, mesh_device, arch, timestamp,
    env (str|None), llm (dict with active_url, occupied, fallback_url).
    """
    return _refresh_state()


@mcp.tool()
def tt_list_devices() -> list:
    """Enumerate all TT devices with arch, index, board type, temperature.

    Runs ``tt-smi -s`` and returns the ``devices`` list from the parsed
    snapshot.  Returns an empty list when tt-smi is unavailable or no
    devices are found.

    Each item in the returned list is a dict with at least:
        index      (int)  — zero-based device index
        board_type (str)  — e.g. "N300", "P300C", "T3K"
        arch       (str)  — "wormhole" | "blackhole"
        temp_c     (float | None) — board temperature in Celsius
    """
    hw = hardware.detect_hardware()
    return hw["devices"] if hw else []


@mcp.tool()
def tt_activate_env(name: str) -> dict:
    """Return a shell activation snippet for the named TT environment.

    The caller (agent or shell hook) should ``eval`` the returned snippet
    to activate the environment in the current shell.  This tool never
    modifies the current process's environment — it only returns text.

    Args:
        name: One of 'metal', 'vllm', 'forge', 'xla'.

    Returns:
        On success: {"env": name, "snippet": "...", "success": True}
        On failure: {"success": False, "error": "...message..."}
    """
    try:
        snippet = envs.get_activation_snippet(name)
        return {"env": name, "snippet": snippet, "success": True}
    except KeyError:
        known = list(envs.ENVIRONMENTS.keys())
        return {
            "success": False,
            "error": f"Unknown env '{name}'. Known: {known}",
        }


@mcp.tool()
def tt_run_workload(script: str, devices: Optional[list] = None) -> dict:
    """Run a Python script on TT hardware via the dispatch priority chain.

    The dispatch chain tries, in order:
        1. tt-ctl (if the binary is on PATH)
        2. Docker tt-inference-server (if image is cached locally)
        3. Direct tt-metal / tt-forge (if ~/tt-metal/python_env exists)
        4. Guided-setup fallback (returns instructions, never blocks)

    Before attempting to occupy hardware, the LLM beer-handoff notification
    is triggered so the user's agent has a fallback URL while hardware loads.

    Args:
        script: Path or inline Python code to execute on TT hardware.
        devices: Optional list of device indices to restrict to.  Currently
                 passed as metadata; actual device pinning depends on the
                 backend selected by the dispatch chain.

    Returns:
        {"method": str, "success": bool, "message": str,
         "pid": int|None, "fallback_llm": str|None}
    """
    state = _get_llm_state()
    result = dispatch.dispatch_workload(script=script, llm_state=state)
    return {
        "method": result.method,
        "success": result.success,
        "message": result.message,
        "pid": result.pid,
        "fallback_llm": state.active_url,
    }


@mcp.tool()
def tt_generate(prompt: str, model: str = "wan2.2", steps: int = 30) -> dict:
    """Submit a generation job (video/image/text) via the dispatch chain.

    Dispatches a generation request using the same priority chain as
    tt_run_workload but with a prompt and model name rather than a script
    path.  Hardware is pre-occupied before dispatch so the beer-handoff
    notification fires and the agent has a fallback LLM URL immediately.

    Args:
        prompt: The generation prompt (text, image description, etc.).
        model:  Model identifier, e.g. 'wan2.2', 'mochi', 'flux',
                'llama3-8b'.  Defaults to 'wan2.2'.
        steps:  Number of inference steps (informational; the backend may
                ignore this if it manages steps internally).

    Returns:
        {"method": str, "success": bool, "message": str,
         "fallback_llm": str|None, "note": str}
    """
    state = _get_llm_state()
    result = dispatch.dispatch_workload(
        prompt=prompt, model=model, llm_state=state
    )
    return {
        "method": result.method,
        "success": result.success,
        "message": result.message,
        "fallback_llm": state.active_url,
        "note": (
            "Hardware may be loading. "
            "Agent can continue via fallback_llm."
        ),
    }


@mcp.tool()
def tt_serve(model: str) -> dict:
    """Start a local inference server for a model.

    Runs the dispatch chain in "serve" mode (model name, no script/prompt):
    tt-ctl → pre-installed tt-inference-server ``run.py`` → cached Docker image
    → guided setup. On a QB2 this lands on ``run.py`` even without tt-ctl, which
    sizes the deployment to the model (``p100`` for ≤14B, ``p300x2`` for
    70B/32B-class) and exposes an OpenAI-compatible API on :8000.

    Poll ``/v1/models`` on :8000 to wait for readiness (first run compiles
    weights, ~3–5 min, longer if downloading).

    Args:
        model: Model name to serve, e.g. 'Qwen3-32B', 'Llama-3.3-70B-Instruct',
               'Llama-3.1-8B-Instruct'.

    Returns:
        {"method": str, "success": bool, "message": str,
         "fallback_llm": str|None}
    """
    state = _get_llm_state()
    result = dispatch.dispatch_workload(prompt=None, model=model, llm_state=state)
    return {
        "method": result.method,
        "success": result.success,
        "message": result.message,
        "fallback_llm": state.active_url,
    }


@mcp.tool()
def tt_diagnose(log_text: str) -> dict:
    """Parse a TT error log and return structured diagnoses with remediation.

    Matches known Tenstorrent error patterns against the provided log text
    and returns structured diagnoses with severity levels and remediation
    steps.  Useful for automated error handling and user guidance.

    Args:
        log_text: Raw log text, e.g. from a failed tt-metal run or
                  tt-smi output.  Can be multiple lines.

    Returns:
        {
            "count": int,
            "diagnoses": [
                {
                    "category":    str,  # e.g. "oom", "driver", "dispatch"
                    "severity":    str,  # "error" | "warning" | "info"
                    "summary":     str,  # one-line human description
                    "remediation": str,  # action to fix the issue
                }
            ],
            "clean": bool,  # True when no issues found
        }
    """
    diagnoses = diag.parse_log(log_text)
    return {
        "count": len(diagnoses),
        "diagnoses": [
            {
                "category": d.category,
                "severity": d.severity,
                "summary": d.summary,
                "remediation": d.remediation,
            }
            for d in diagnoses
        ],
        "clean": len(diagnoses) == 0,
    }


@mcp.tool()
def tt_doctor() -> dict:
    """Full system health check: hardware, hugepages, shm, env, and LLM.

    Aggregates diagnostics from multiple subsystems into a single report.
    Intended as a first-step triage tool when something isn't working.

    Checks:
      - TT hardware detection and mesh device type
      - /proc/sys/vm/nr_hugepages presence (required for tt-metal)
      - /dev/shm for stale tenstorrent* files (can block device init)
      - Active Python environment name
      - LLM endpoint availability and routing state

    Returns:
        {
            "hardware":        dict | None,  # full tt-smi snapshot
            "mesh_device":     str | None,   # e.g. "T3K", "N300"
            "hugepages_ok":    bool,
            "shm_clean":       bool,         # True if no stale shm files
            "active_env":      str | None,
            "known_envs":      list[str],
            "llm":             dict,         # LLMState.to_dict() output
            "tt_smi_available": bool,
        }
    """
    hw = hardware.detect_hardware()
    # Hugepages are required for DMA ring allocation on WH/BH hardware.
    hugepages_ok = Path("/proc/sys/vm/nr_hugepages").exists()
    # Stale tenstorrent* shm files prevent device re-init after a crash.
    shm_clean = not any(Path("/dev/shm").glob("tenstorrent*"))
    active_env = envs.detect_active_env()
    llm = _get_llm_state()
    return {
        "hardware": hw,
        "mesh_device": hardware.get_mesh_device(),
        "hugepages_ok": hugepages_ok,
        "shm_clean": shm_clean,
        "active_env": active_env,
        "known_envs": list(envs.ENVIRONMENTS.keys()),
        "llm": llm.to_dict(),
        "tt_smi_available": hardware.has_tt_smi(),
    }


@mcp.tool()
def tt_logs(service: Optional[str] = None) -> dict:
    """Tail logs for a running TT service.

    Delegates to ``tt-ctl logs`` to fetch recent log lines for a named
    service.  Returns the last 50 lines.

    Args:
        service: Service name, one of 'wan2.2', 'mochi', 'docker', or None
                 for all services.

    Returns:
        {"success": bool, "output": str}  on success
        {"success": False, "error": str}  if tt-ctl is not available or
                                           the subprocess fails
    """
    if _shutil.which("tt-ctl"):
        cmd = (
            ["tt-ctl", "logs"]
            + ([service] if service else [])
            + ["--lines", "50"]
        )
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            return {
                "success": True,
                "output": result.stdout or result.stderr,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    return {"success": False, "error": "tt-ctl not found"}


@mcp.tool()
def tt_reset_devices() -> dict:
    """Reset all TT devices via tt-smi -r.

    Performs a hard reset of all connected Tenstorrent devices.  This clears
    stale shared-memory regions and re-initialises the PCIe interface.  Use
    after a crashed workload left devices in an unusable state.

    Warning: any running workloads will be killed by the reset.

    Returns:
        {"success": bool, "output": str}   — output from tt-smi -r
        {"success": False, "error": str}   — if tt-smi is unavailable
    """
    if not hardware.has_tt_smi():
        return {"success": False, "error": "tt-smi not found"}
    try:
        result = subprocess.run(
            ["tt-smi", "-r"], capture_output=True, text=True, timeout=30
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout or result.stderr,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@mcp.tool()
def tt_knowledge(query: str, hardware_filter: Optional[str] = None) -> dict:
    """Search the local TT knowledge corpus for documentation and lessons.

    Queries the SQLite FTS corpus built by ``tt-warp sync``.  The corpus
    contains lessons from the tt-vscode-toolkit skills library and crawled
    pages from tenstorrent.github.io.

    Results are filtered to the detected hardware platform by default so
    that, e.g., a Blackhole-only lesson won't appear when querying on a
    Wormhole machine.  Pass hardware_filter="all" to disable filtering.

    Args:
        query:           Free-text search query.
        hardware_filter: Override hardware filter.  Typical values:
                         "n300", "t3k", "p300c", "galaxy".
                         Pass None to auto-detect from connected hardware.

    Returns:
        {
            "query":           str,
            "hardware_filter": str | None,
            "results": [
                {
                    "lesson_id": str,
                    "title":     str,
                    "content":   str,   # first 800 chars of matched chunk
                    "status":    str,   # "validated" | "experimental" | …
                }
            ],
            "error": str,  # only present when corpus is unavailable
        }
    """
    db = _get_db()
    if db is None:
        return {
            "results": [],
            "error": "Knowledge corpus not found. Run: tt-warp sync",
        }
    # Use the caller's override, or fall back to auto-detecting connected hw.
    hw = hardware_filter or hardware.get_mesh_device()
    results = db.search(query, hardware=hw, top_k=5)
    return {
        "query": query,
        "hardware_filter": hw,
        "results": [
            {
                "lesson_id": r["lesson_id"],
                "title": r["title"],
                "content": r["content"][:800],
                "status": r["status"],
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the FastMCP server using stdio transport (default for MCP)."""
    mcp.run()


if __name__ == "__main__":
    main()
