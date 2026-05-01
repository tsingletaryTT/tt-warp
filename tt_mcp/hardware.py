"""Hardware detection for Tenstorrent devices via tt-smi.

This module wraps ``tt-smi -s`` (snapshot mode) to discover connected
Tenstorrent accelerator boards, normalise their metadata, and derive
higher-level concepts like the mesh device name (e.g. "T3K") and the
hardware generation (Blackhole vs Wormhole).

Public API
----------
detect_hardware() -> Optional[dict]
    Run ``tt-smi -s`` and return a structured snapshot, or None when
    no tt-smi binary is found or an error occurs.

get_mesh_device() -> Optional[str]
    Return the normalised mesh device name for the detected hardware.

is_blackhole() -> bool
    Return True when the primary board is Blackhole-generation.

is_wormhole() -> bool
    Return True when the primary board is Wormhole-generation.

write_state(state_path, extra=None) -> dict
    Persist a hardware snapshot to a JSON file and return the state dict.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Architecture classification sets
# ---------------------------------------------------------------------------

# Blackhole board type strings as returned by tt-smi (upper-cased after parse).
# Blackhole is Tenstorrent's second-generation ASIC architecture.
_BH_TYPES: frozenset[str] = frozenset(
    {"P100", "P100C", "P150", "P150C", "P300", "P300C"}
)

# Wormhole board type strings (upper-cased after parse).
# Wormhole is Tenstorrent's first-generation production ASIC architecture.
_WH_TYPES: frozenset[str] = frozenset({"N150", "N300", "T3K"})

# N300 chip-count → mesh device name mapping.
# An N300 is a dual-chip board; 4 such boards wired into a galaxy ring = T3K.
_N300_MESH: dict[int, str] = {2: "N300", 4: "N300X4", 8: "T3K"}

# N150 chip-count → mesh device name mapping.
_N150_MESH: dict[int, str] = {1: "N150", 2: "N300", 4: "N150X4", 8: "T3K"}

# Blackhole P-series chip-count → mesh device name mapping.
# A P300C is a dual-chip Blackhole board; 2 chips = P300 mesh device.
_P300C_MESH: dict[int, str] = {1: "P100", 2: "P300", 4: "P150X4"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def has_tt_smi() -> bool:
    """Return True if the ``tt-smi`` binary is present on PATH.

    Uses ``shutil.which`` so that callers can monkeypatch it in tests without
    needing to shadow the entire ``shutil`` module.
    """
    return shutil.which("tt-smi") is not None


def _parse_device(idx: int, dev: dict) -> dict:
    """Extract a normalised device dict from a single tt-smi device_info entry.

    Parameters
    ----------
    idx:
        Zero-based device index within the snapshot.
    dev:
        Raw device_info element from the parsed JSON.

    Returns
    -------
    dict with keys: index, type, bus_id, temperature, power, firmware.
    ``type`` is upper-cased for consistent downstream comparisons.
    """
    board = dev.get("board_info", {})
    telem = dev.get("telemetry", {})
    fw = dev.get("firmwares", {})
    return {
        "index": idx,
        # Normalise to uppercase so callers can compare against _BH_TYPES etc.
        "type": board.get("board_type", "unknown").upper(),
        "bus_id": board.get("bus_id", "unknown"),
        "temperature": telem.get("asic_temperature", 0.0),
        "power": telem.get("power", 0.0),
        "firmware": fw.get("fw_bundle_version", "unknown"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_hardware() -> Optional[dict]:
    """Run ``tt-smi -s`` and return a structured hardware snapshot.

    The snapshot dict has the following shape::

        {
            "devices": [
                {
                    "index": 0,
                    "type": "P300C",        # upper-cased board_type
                    "bus_id": "0000:01:00.0",
                    "temperature": 65.5,    # asic_temperature in °C
                    "power": 120.3,         # board power in W
                    "firmware": "80.15.0.0",
                },
                ...
            ],
            "count": 2,             # total number of chips
            "primary_type": "P300C",  # board_type of device[0]
        }

    Returns
    -------
    None when:
    - ``tt-smi`` is not on PATH (checked via :func:`has_tt_smi`).
    - The process exits with a non-zero return code.
    - The output cannot be parsed as JSON.
    - The process times out (5 s).
    - No devices are reported in the snapshot.
    """
    if not has_tt_smi():
        return None

    try:
        result = subprocess.run(
            ["tt-smi", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)
        devices = [
            _parse_device(idx, dev)
            for idx, dev in enumerate(data.get("device_info", []))
        ]

        if not devices:
            return None

        return {
            "devices": devices,
            "count": len(devices),
            # Callers use primary_type as the authoritative board family.
            "primary_type": devices[0]["type"],
        }

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def is_blackhole() -> bool:
    """Return True when the primary board belongs to the Blackhole architecture.

    Blackhole board types: P100, P100C, P150, P150C, P300, P300C.
    Returns False when no hardware is detected.
    """
    hw = detect_hardware()
    return hw is not None and hw["primary_type"] in _BH_TYPES


def is_wormhole() -> bool:
    """Return True when the primary board belongs to the Wormhole architecture.

    Wormhole board types: N150, N300 (and the T3K galaxy ring).
    Returns False when no hardware is detected.
    """
    hw = detect_hardware()
    return hw is not None and hw["primary_type"] in _WH_TYPES


def _mesh_from_hw(hw: dict) -> Optional[str]:
    """Compute the mesh device name from an already-fetched hardware dict.

    This is the pure mapping logic shared by :func:`get_mesh_device` and
    :func:`write_state`.  Callers that have already run ``detect_hardware()``
    can call this directly to avoid a redundant ``tt-smi`` subprocess.

    Parameters
    ----------
    hw:
        A non-None hardware dict as returned by :func:`detect_hardware`.

    Returns
    -------
    The mesh device name string, or None when the board type is unrecognised.

    =========  ======  ===========
    board_type  count   mesh name
    =========  ======  ===========
    N150        1       N150
    N150        2       N300
    N150        8       T3K
    N300        2       N300
    N300        8       T3K
    P300C       1       P100
    P300C       2       P300
    =========  ======  ===========
    """
    board = hw["primary_type"]
    count = hw["count"]

    if board == "N150":
        return _N150_MESH.get(count, "N150")

    if board == "N300":
        return _N300_MESH.get(count, "N300")

    if board in ("P300C", "P150C", "P150"):
        return _P300C_MESH.get(count, "P150")

    # Fallback: strip trailing 'C' suffix (e.g. "P100C" → "P100") for display.
    return board.rstrip("C") if board.endswith("C") else board


def get_mesh_device() -> Optional[str]:
    """Return the normalised mesh device name for the detected hardware.

    Runs ``tt-smi -s`` once, then delegates to :func:`_mesh_from_hw` for the
    board-type → mesh-name mapping.

    Returns
    -------
    The mesh device name string, or None when no hardware is detected.
    """
    hw = detect_hardware()
    if not hw:
        return None
    return _mesh_from_hw(hw)


def write_state(state_path: Path, extra: Optional[dict] = None) -> dict:
    """Persist a hardware snapshot to a JSON file and return the state dict.

    Runs ``tt-smi -s`` exactly once — the same snapshot is used to populate
    both ``"hardware"`` and ``"mesh_device"`` fields, avoiding a second
    subprocess call (and the risk of an inconsistent snapshot between the two).

    The directory is created automatically if it does not exist.  An ``extra``
    mapping can supply additional top-level keys that are merged into the state
    before writing.

    Parameters
    ----------
    state_path:
        Destination path for the JSON file (e.g. ``~/.tt-warp/state.json``).
    extra:
        Optional dict merged into the state at the top level.

    Returns
    -------
    The state dict that was written to disk.
    """
    hw = detect_hardware()
    # Derive mesh device from the already-fetched hw dict to avoid a second
    # tt-smi subprocess call (get_mesh_device() would call detect_hardware()
    # again, giving a different snapshot and wasting a subprocess round-trip).
    mesh = _mesh_from_hw(hw) if hw else None
    state: dict = {
        "hardware": hw,
        "mesh_device": mesh,
        # Wall-clock timestamp so callers can gauge staleness.
        "timestamp": time.time(),
    }
    if extra:
        state.update(extra)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    return state
