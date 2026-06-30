"""
Manages a Qwen3-0.6B CPU inference sidecar for the beer handoff pattern.

Checks for an already-running sidecar (tt-local-generator's prompt_server
or any compatible server) before spawning a new process. The optional
[sidecar] extras (transformers, fastapi, uvicorn) are only needed when no
existing sidecar is found and auto-spawn is requested.

Port note: the sidecar lives on :8011, deliberately NOT :8001 — on a QB2
(and any tt-inference-server host) :8001 is the inference server's prompt
server, so binding it would collide. :8000 stays reserved for the primary
TT-silicon vLLM server.
"""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

_SIDECAR_PORT = 8011
_STARTUP_TIMEOUT = 60  # seconds to wait for sidecar to become ready
_PROBE_TIMEOUT = 1.5


def find_existing_sidecar() -> Optional[str]:
    """Return URL if a compatible server is already on :8011, else None."""
    url = f"http://localhost:{_SIDECAR_PORT}"
    try:
        r = requests.get(f"{url}/v1/models", timeout=_PROBE_TIMEOUT)
        if r.status_code == 200:
            return url
    except Exception:
        pass
    return None


class CpuSidecar:
    """Lifecycle manager for the CPU-based Qwen3 sidecar process."""

    def __init__(self, model: str = "Qwen/Qwen3-0.6B", port: int = _SIDECAR_PORT):
        self.model = model
        self.port = port
        self._proc: Optional[subprocess.Popen] = None

    @property
    def url(self) -> Optional[str]:
        existing = find_existing_sidecar()
        if existing:
            return existing
        if self._proc is not None and self._proc.poll() is None:
            return f"http://localhost:{self.port}"
        return None

    def ensure_running(self) -> Optional[str]:
        """Start the sidecar if not already running. Returns URL or None."""
        existing = find_existing_sidecar()
        if existing:
            return existing
        return self._spawn()

    def _spawn(self) -> Optional[str]:
        """Spawn prompt_server.py as a subprocess. Requires [sidecar] extras."""
        server_script = Path(__file__).parent / "_prompt_server.py"
        if not server_script.exists():
            # Try tt-local-generator's prompt_server if available
            alt = Path("~/code/tt-local-generator/app/prompt_server.py").expanduser()
            if alt.exists():
                server_script = alt
            else:
                return None  # no sidecar script available

        self._proc = subprocess.Popen(
            [sys.executable, str(server_script),
             "--model", self.model, "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for readiness
        deadline = time.time() + _STARTUP_TIMEOUT
        while time.time() < deadline:
            # If process died early (e.g. import error, port conflict), give up
            # immediately rather than burning the full timeout and then calling
            # terminate() on a dead process (which is unsafe on some platforms).
            if self._proc.poll() is not None:
                self._proc = None
                return None
            url = find_existing_sidecar()
            if url:
                return url
            time.sleep(2)
        self._proc.terminate()
        self._proc = None
        return None

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            # Wait for the process to actually exit so the port is released
            # before returning.  Fall back to SIGKILL if it lingers.
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
