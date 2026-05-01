"""
LLM endpoint probing and "beer handoff" state machine.

The beer handoff pattern: when TT hardware is about to be occupied by a
workload, the agent needs an LLM to continue talking to the user.

- pre_occupy()         marks hardware as busy → agent routes to CPU sidecar
                       (e.g. Qwen3 on :8001)
- hardware_released()  marks hardware as free → agent routes back to TT
                       silicon LLM on :8000

probe_endpoints() sniffs all candidate ports (localhost only, never remote)
and returns an LLMState describing what is available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

# Ordered list of (port, role) pairs probed at startup.
# "primary" is the TT silicon inference server (high-throughput, metal-backed).
# "sidecar"/"ollama"/"generic" are CPU fallback candidates used during hardware
# occupancy.  The first matching port wins for each role bucket.
CANDIDATE_PORTS = [
    (8000, "primary"),   # tt-inference-server on TT silicon
    (8001, "sidecar"),   # Qwen3 CPU sidecar
    (11434, "ollama"),   # local Ollama instance
    (8080, "generic"),   # any other OpenAI-compatible server
]

# Per-port probe timeout in seconds — fast enough not to block startup, long
# enough to survive a loaded localhost.
_TIMEOUT = 1.5


@dataclass
class LLMState:
    """
    Tracks the two LLM endpoints (primary/fallback) and the hardware-busy flag.

    Attributes
    ----------
    primary_url:    Base URL of the TT silicon inference server, or None if
                    not detected.
    primary_model:  First model ID returned by the primary server's /v1/models.
    fallback_url:   Base URL of the CPU sidecar (or any non-primary server).
    fallback_model: First model ID returned by the fallback server's /v1/models.
    hardware_busy:  True while a TT workload is running and the primary LLM
                    endpoint is unavailable.  Toggled by pre_occupy() /
                    hardware_released().
    """

    primary_url: Optional[str] = None
    primary_model: Optional[str] = None
    fallback_url: Optional[str] = None
    fallback_model: Optional[str] = None
    hardware_busy: bool = False

    # ------------------------------------------------------------------
    # Computed routing properties
    # ------------------------------------------------------------------

    @property
    def active_url(self) -> Optional[str]:
        """
        Return the URL the agent should currently use.

        During hardware occupancy the fallback (CPU sidecar) is preferred.
        When hardware is free, the primary TT silicon server is preferred.
        If neither bucket is populated, returns None.
        """
        if self.hardware_busy and self.fallback_url:
            return self.fallback_url
        return self.primary_url or self.fallback_url

    @property
    def active_model(self) -> Optional[str]:
        """
        Return the model ID that pairs with active_url.

        Mirrors the same logic as active_url so callers don't need to
        reconstruct which URL → which model themselves.
        """
        if self.hardware_busy and self.fallback_model:
            return self.fallback_model
        return self.primary_model or self.fallback_model

    # ------------------------------------------------------------------
    # Beer handoff state transitions
    # ------------------------------------------------------------------

    def pre_occupy(self) -> None:
        """
        Signal that TT hardware is about to be occupied by a workload.

        Sets hardware_busy=True.  Subsequent calls to active_url / active_model
        will return the fallback (CPU sidecar) endpoint so the agent can
        continue responding to the user while the silicon is busy.
        """
        self.hardware_busy = True

    def hardware_released(self) -> None:
        """
        Signal that the TT hardware workload has finished.

        Clears hardware_busy.  Subsequent calls to active_url / active_model
        return to the primary TT silicon endpoint.
        """
        self.hardware_busy = False

    # ------------------------------------------------------------------
    # Serialisation helper
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain-dict snapshot suitable for JSON serialisation."""
        return {
            "primary": self.primary_url,
            "primary_model": self.primary_model,
            "fallback": self.fallback_url,
            "fallback_model": self.fallback_model,
            "hardware_busy": self.hardware_busy,
            "active": self.active_url,
            "active_model": self.active_model,
        }


# ---------------------------------------------------------------------------
# Probing helpers
# ---------------------------------------------------------------------------

def _probe_port(port: int) -> Optional[tuple[str, str]]:
    """
    Check whether an OpenAI-compatible inference server is listening on *port*.

    Sends a single GET /v1/models request.  On success returns (base_url,
    first_model_id).  On any failure (connection refused, timeout, non-200
    response, malformed JSON) returns None silently — callers should treat a
    missing result as "nothing running here".

    Parameters
    ----------
    port:
        TCP port to probe on localhost.

    Returns
    -------
    (url, model_id) if the server responded correctly, else None.
    """
    url = f"http://localhost:{port}"
    try:
        r = requests.get(f"{url}/v1/models", timeout=_TIMEOUT)
        if r.status_code == 200:
            models = r.json().get("data", [])
            # Use the first listed model id, or a safe sentinel when the
            # server returns an empty model list.
            model_id = models[0]["id"] if models else "unknown"
            return url, model_id
    except Exception:
        # Intentionally swallow every exception (ConnectionError, Timeout,
        # JSONDecodeError, KeyError, …) — probing is best-effort.
        pass
    return None


def probe_endpoints() -> LLMState:
    """
    Probe all candidate ports and return an LLMState describing what was found.

    The probe is strictly localhost — it never contacts remote endpoints.
    Ports are tried in CANDIDATE_PORTS order; within each role bucket only the
    first responding server is recorded.

    Returns
    -------
    LLMState
        Populated with primary_url/model and/or fallback_url/model depending
        on which ports answered.  hardware_busy starts as False.
    """
    state = LLMState()

    for port, role in CANDIDATE_PORTS:
        result = _probe_port(port)
        if result is None:
            # Nothing listening on this port — skip.
            continue

        url, model = result

        if role == "primary" and state.primary_url is None:
            # First working TT silicon server wins the primary slot.
            state.primary_url = url
            state.primary_model = model
        elif role in ("sidecar", "ollama", "generic") and state.fallback_url is None:
            # First working non-primary server wins the fallback slot.
            state.fallback_url = url
            state.fallback_model = model

    return state
