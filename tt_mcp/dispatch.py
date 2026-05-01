"""
dispatch.py — Workload dispatch priority chain for tt-warp.

Priority order:
  1. tt-ctl (CLI tool, highest priority — handles all TT hardware abstraction)
  2. Docker tt-inference-server (if image is locally cached)
  3. Direct tt-metal / tt-forge (if the Python env is installed)
  4. Guided setup (nothing found — tell user to run tt-setup)

Before any hardware-occupying dispatch step (1–3), this module calls
``llm_state.pre_occupy()`` so the beer-handoff notification is triggered.
After the workload completes (or fails), it calls ``llm_state.hardware_released()``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tt_mcp.llm import LLMState


@dataclass
class DispatchResult:
    """
    Result returned by :func:`dispatch_workload`.

    Attributes:
        method:  Which backend handled the call.
                 One of: ``"tt-ctl"``, ``"docker"``, ``"direct"``, ``"none"``.
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
    hw_args = ["--device", "/dev/tenstorrent/0"]
    cmd = [
        "docker", "run", "--rm", "-d",
        "-p", "8000:8000",
        "--privileged",
        "-v", "/dev/hugepages:/dev/hugepages",
        *hw_args,
        "ghcr.io/tenstorrent/tt-inference-server:latest",
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
    # ② Docker tt-inference-server image cached locally
    # ------------------------------------------------------------------
    if _docker_image_available():
        if llm_state:
            llm_state.pre_occupy()
        result = _launch_docker(model or "default", prompt)
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
