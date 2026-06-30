"""
dispatch.py — Workload dispatch priority chain for tt-warp.

Priority order:
  1. tt-ctl (CLI tool, highest priority — handles all TT hardware abstraction)
  2. tt-inference-server run.py launcher (pre-installed on QB2; serve intent only)
  3. Docker tt-inference-server (if image is locally cached)
  4. Direct tt-metal / tt-forge (if the Python env is installed)
  5. Guided setup (nothing found — tell user to run tt-setup)

Before any hardware-occupying dispatch step (1–3), this module calls
``llm_state.pre_occupy()`` so the beer-handoff notification is triggered.
After the workload completes (or fails), it calls ``llm_state.hardware_released()``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tt_mcp.llm import LLMState

# Limit the public API surface to only the symbols callers should import.
__all__ = ["DispatchResult", "dispatch_workload"]

# Locations where the tt-inference-server run.py launcher is pre-installed.
# A QB2 ships it at the first path; a manual clone (per the QB2 guide's
# Llama-70B lesson) lands at the second.
_RUN_PY_CANDIDATES = [
    "~/.local/lib/tt-inference-server/run.py",
    "~/code/tt-inference-server/run.py",
]

# Fallback raw-docker image, used only when run.py is absent but an image is
# cached. Kept as a constant so it is easy to bump in one place.
_INFERENCE_IMAGE = "ghcr.io/tenstorrent/tt-inference-server:latest"


@dataclass
class DispatchResult:
    """
    Result returned by :func:`dispatch_workload`.

    Attributes:
        method:  Which backend handled the call.  One of: ``"tt-ctl"``,
                 ``"inference-server"`` (run.py launcher), ``"docker"``,
                 ``"direct"``, ``"none"``.
        success: ``True`` if the backend accepted / launched the workload
                 without error; ``False`` otherwise.
        message: Human-readable summary (stdout/stderr excerpt, error text,
                 or guidance for the user).
        pid:     Process ID of a background child process, when applicable
                 (e.g. a ``Popen``-launched direct script).  ``None`` if not
                 relevant.
    """

    method: str          # "tt-ctl" | "docker" | "direct" | "none"
    success: bool
    message: str
    pid: Optional[int] = None


# ---------------------------------------------------------------------------
# Internal probe helpers
# ---------------------------------------------------------------------------

def _docker_image_available() -> bool:
    """
    Return ``True`` when the tt-inference-server Docker image is already
    present in the local image cache (no pull needed).

    Uses ``docker images --format`` to list repository names and checks for
    the ``tt-inference-server`` substring.  Times out after 5 s so a slow
    Docker daemon doesn't stall the caller.
    """
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "tt-inference-server" in result.stdout
    except Exception:
        # Docker not installed, daemon not running, etc. — treat as absent.
        return False


def _run_py_path() -> Optional[Path]:
    """Return the path to a pre-installed tt-inference-server ``run.py``.

    Checks the QB2 install location first, then a manual clone. Returns None
    when neither is present (the caller then falls through to raw Docker).
    """
    for cand in _RUN_PY_CANDIDATES:
        p = Path(cand).expanduser()
        if p.exists():
            return p
    return None


def _tt_device_for(model: Optional[str]) -> str:
    """Map a model name to the tt-inference-server ``--tt-device`` value.

    QB2 presents each Blackhole chip as a ``p100``; the whole box (both p300c
    cards, all four chips) is ``p300x2``. 70B- and 32B-class models need the
    whole box; smaller models fit on a single chip, leaving the others free.
    """
    name = (model or "").lower()
    if "70b" in name or "32b" in name:
        return "p300x2"
    return "p100"


def _launch_run_py(run_py: Path, model: str) -> DispatchResult:
    """Start a model server via the pre-installed run.py launcher.

    run.py foregrounds the server (no ``-d``), so it is launched detached via
    Popen; the caller polls ``/v1/models`` on :8000 for readiness. The chosen
    ``--tt-device`` is derived from the model's size class. HF_TOKEN is
    inherited from the parent environment for gated weights.
    """
    device = _tt_device_for(model)
    cmd = [
        sys.executable, str(run_py),
        "--model", model,
        "--tt-device", device,
        "--workflow", "server",
        "--docker-server",
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return DispatchResult(
            method="inference-server",
            success=True,
            message=(
                f"tt-inference-server starting {model} on {device} "
                f"(pid {proc.pid}). First run compiles weights (~3-5 min, "
                f"longer if downloading). Poll http://localhost:8000/v1/models."
            ),
            pid=proc.pid,
        )
    except Exception as e:
        return DispatchResult(
            method="inference-server", success=False, message=str(e)
        )


def _metal_installed() -> bool:
    """
    Return ``True`` when a tt-metal Python environment exists at the
    canonical location ``~/tt-metal/python_env``.

    This is the standard layout produced by the tt-metal installer and build
    scripts.  If it is absent the caller should fall back to guided setup.
    """
    return Path("~/tt-metal/python_env").expanduser().exists()


# ---------------------------------------------------------------------------
# Docker launch helper
# ---------------------------------------------------------------------------

def _launch_docker(model: str, prompt: Optional[str] = None) -> DispatchResult:
    """
    Start the tt-inference-server container in detached mode.

    The container is launched with:
    * ``--privileged`` and ``/dev/hugepages`` mount — required by the TT
      runtime for huge-page DMA buffers.
    * ``/dev/tenstorrent/0`` device passthrough — grants exclusive hardware
      access to the container.
    * Port 8000 exposed — the inference server's REST/gRPC endpoint.

    Args:
        model:  Model identifier forwarded to the server (currently stored
                for future use; not yet passed as an env-var).
        prompt: Optional initial prompt (reserved for future use).

    Returns:
        :class:`DispatchResult` with ``method="docker"``.  On success the
        message tells the caller to poll ``http://localhost:8000/health``.
    """
    # Pass the whole /dev/tenstorrent dir (all chips), the 1G hugepages mount
    # the TT runtime requires, and HF_TOKEN for gated weights. --tt-device sizes
    # the deployment to the model. This is the fallback when run.py is absent.
    device = _tt_device_for(model)
    cmd = [
        "docker", "run", "--rm", "-d",
        "-p", "8000:8000",
        "--ipc", "host",
        "--device", "/dev/tenstorrent",
        "-v", "/dev/hugepages-1G:/dev/hugepages-1G",
        "-e", "HF_TOKEN",
        _INFERENCE_IMAGE,
        "--model", model,
        "--tt-device", device,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            container_id = result.stdout.strip()
            return DispatchResult(
                method="docker",
                success=True,
                message=(
                    f"tt-inference-server starting "
                    f"(container {container_id[:12]}). "
                    f"Poll http://localhost:8000/health for readiness."
                ),
                pid=None,
            )
        # Non-zero exit — surface Docker's stderr as the error message.
        return DispatchResult(
            method="docker",
            success=False,
            message=result.stderr.strip(),
        )
    except Exception as e:
        return DispatchResult(method="docker", success=False, message=str(e))


# ---------------------------------------------------------------------------
# Public dispatch entry-point
# ---------------------------------------------------------------------------

def dispatch_workload(
    prompt: Optional[str] = None,
    model: Optional[str] = None,
    script: Optional[str] = None,
    llm_state: Optional[LLMState] = None,
) -> DispatchResult:
    """
    Dispatch a workload through the priority chain.

    The chain is evaluated top-to-bottom and stops at the first available
    backend.  Before acquiring TT hardware (steps 1–3), this function calls
    ``llm_state.pre_occupy()`` so the beer-handoff notification is sent to
    the user.  If the dispatch fails, ``llm_state.hardware_released()`` is
    called to undo the occupation state.

    Priority chain:
        1. **tt-ctl** — if the ``tt-ctl`` binary is on ``$PATH``, it handles
           everything: model loading, scheduling, power management.
        2. **Docker tt-inference-server** — if the image is locally cached,
           launch it detached; the caller polls ``/health`` for readiness.
        3. **Direct tt-metal / tt-forge** — if ``~/tt-metal/python_env``
           exists, run ``script`` with the system Python in a ``Popen``
           child.  The process runs asynchronously; the PID is returned.
        4. **Guided setup** — nothing found; return ``method="none"`` with
           a message directing the user to run the ``tt-setup`` skill.

    Args:
        prompt:    Natural-language prompt forwarded to the model/server.
        model:     Model identifier (e.g. ``"wan2.2"``).
        script:    Path to a Python script for direct or tt-ctl execution.
        llm_state: Optional :class:`~tt_mcp.llm.LLMState` used to signal
                   hardware occupation / release for beer-handoff.

    Returns:
        A :class:`DispatchResult` describing which backend handled the
        workload and whether it succeeded.
    """

    # ------------------------------------------------------------------
    # ① tt-ctl present on PATH
    # ------------------------------------------------------------------
    if shutil.which("tt-ctl"):
        if llm_state:
            llm_state.pre_occupy()

        # Build command: prefer explicit script/prompt, fall back to status.
        cmd = ["tt-ctl"]
        if script:
            cmd += ["run", script]
        elif prompt and model:
            cmd += ["run", prompt, "--model", model]
        else:
            cmd += ["status"]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            if llm_state:
                llm_state.hardware_released()
            return DispatchResult(
                method="tt-ctl",
                success=result.returncode == 0,
                message=result.stdout or result.stderr,
            )
        except Exception as e:
            if llm_state:
                llm_state.hardware_released()
            return DispatchResult(method="tt-ctl", success=False, message=str(e))

    # ------------------------------------------------------------------
    # ② Pre-installed tt-inference-server run.py launcher (QB2 default)
    #    Only for "serve this model" intent — a bare model name with no script
    #    and no generation prompt. tt_serve() hits this; tt_generate() (which
    #    passes a prompt for video/image gen) and tt_run_workload() (script) do
    #    not, so they keep their existing dispatch behaviour.
    # ------------------------------------------------------------------
    if model and not script and not prompt:
        run_py = _run_py_path()
        if run_py:
            if llm_state:
                llm_state.pre_occupy()
            try:
                result = _launch_run_py(run_py, model)
            except Exception as e:
                if llm_state:
                    llm_state.hardware_released()
                return DispatchResult(
                    method="inference-server", success=False, message=str(e)
                )
            # On launch failure the hardware was never occupied — release.
            if llm_state and not result.success:
                llm_state.hardware_released()
            return result

    # ------------------------------------------------------------------
    # ③ Docker tt-inference-server image cached locally
    # ------------------------------------------------------------------
    if _docker_image_available():
        if llm_state:
            llm_state.pre_occupy()
        # Wrap in try/except so that an unexpected exception from
        # _launch_docker never leaves hardware_busy permanently stuck True.
        try:
            result = _launch_docker(model or "default", prompt)
        except Exception as e:
            if llm_state:
                llm_state.hardware_released()
            return DispatchResult(method="docker", success=False, message=str(e))
        # On launch failure the hardware was never actually occupied, so
        # release the occupation state to keep llm_state consistent.
        if llm_state and not result.success:
            llm_state.hardware_released()
        return result

    # ------------------------------------------------------------------
    # ③ Direct tt-metal / tt-forge execution
    # ------------------------------------------------------------------
    if script and _metal_installed():
        if llm_state:
            llm_state.pre_occupy()
        try:
            # Launch asynchronously — caller may monitor via ``pid``.
            proc = subprocess.Popen(
                ["python", script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if llm_state:
                llm_state.hardware_released()
            return DispatchResult(
                method="direct",
                success=True,
                message=f"Running {script} (pid {proc.pid})",
                pid=proc.pid,
            )
        except Exception as e:
            if llm_state:
                llm_state.hardware_released()
            return DispatchResult(method="direct", success=False, message=str(e))

    # ------------------------------------------------------------------
    # ④ Nothing found — guide user to install a TT runtime
    # ------------------------------------------------------------------
    return DispatchResult(
        method="none",
        success=False,
        message=(
            "No TT runtime found. "
            "Use the tt-setup skill to install one."
        ),
    )
