import json
import pytest
from pathlib import Path


# Fixture data representing a two-chip P300C Wormhole board as returned by
# `tt-smi -s`. Key names match the real tt-smi JSON output:
#   - "asic_temperature" (not ASIC_TEMPERATURE)
#   - "power"            (not INPUT_POWER)
TT_SMI_P300C = {
    "device_info": [
        {
            "board_info": {"board_type": "p300c", "bus_id": "0000:01:00.0"},
            "telemetry": {"asic_temperature": 65.5, "power": 120.3},
            "firmwares": {"fw_bundle_version": "80.15.0.0"},
        },
        {
            "board_info": {"board_type": "p300c", "bus_id": "0000:01:00.1"},
            "telemetry": {"asic_temperature": 67.2, "power": 118.1},
            "firmwares": {"fw_bundle_version": "80.15.0.0"},
        },
    ]
}

# Fixture data representing a T3K galaxy ring: 4x n300 boards (dual-chip),
# yielding 8 chips total.  Each entry carries board_type "n300" — NOT "n150"
# (n150 is a single-chip board; n300 is the dual-chip variant used in T3K).
TT_SMI_WORMHOLE_T3K = {
    "device_info": [
        {
            "board_info": {"board_type": "n300", "bus_id": f"0000:0{i}:00.0"},
            "telemetry": {"asic_temperature": 55.0 + i, "power": 80.0},
            "firmwares": {"fw_bundle_version": "80.15.0.0"},
        }
        for i in range(8)
    ]
}


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / ".tt-warp"
    d.mkdir()
    return d


@pytest.fixture
def smi_p300c(monkeypatch):
    """Patch subprocess.run to return a 2-chip P300C tt-smi snapshot.

    The fake only accepts ``tt-smi -s`` calls; any other subprocess invocation
    will raise AssertionError to catch accidental broad patching.
    """
    import subprocess

    result = subprocess.CompletedProcess(
        args=["tt-smi", "-s"], returncode=0,
        stdout=json.dumps(TT_SMI_P300C), stderr=""
    )

    def fake_tt_smi(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        assert cmd[:2] == ["tt-smi", "-s"], f"Unexpected subprocess call: {cmd}"
        return result

    monkeypatch.setattr(subprocess, "run", fake_tt_smi)
    return TT_SMI_P300C


@pytest.fixture
def smi_t3k(monkeypatch):
    """Patch subprocess.run to return an 8-chip T3K (4x n300) tt-smi snapshot.

    The fake only accepts ``tt-smi -s`` calls; any other subprocess invocation
    will raise AssertionError to catch accidental broad patching.
    """
    import subprocess

    result = subprocess.CompletedProcess(
        args=["tt-smi", "-s"], returncode=0,
        stdout=json.dumps(TT_SMI_WORMHOLE_T3K), stderr=""
    )

    def fake_tt_smi(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        assert cmd[:2] == ["tt-smi", "-s"], f"Unexpected subprocess call: {cmd}"
        return result

    monkeypatch.setattr(subprocess, "run", fake_tt_smi)
    return TT_SMI_WORMHOLE_T3K
