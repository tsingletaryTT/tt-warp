import json
import pytest
from pathlib import Path


TT_SMI_SINGLE_BH = {
    "device_info": [
        {
            "board_info": {"board_type": "p300c", "bus_id": "0000:01:00.0"},
            "telemetry": {"ASIC_TEMPERATURE": 65.5, "INPUT_POWER": 120.3},
            "firmwares": {"fw_bundle_version": "80.15.0.0"},
        },
        {
            "board_info": {"board_type": "p300c", "bus_id": "0000:01:00.1"},
            "telemetry": {"ASIC_TEMPERATURE": 67.2, "INPUT_POWER": 118.1},
            "firmwares": {"fw_bundle_version": "80.15.0.0"},
        },
    ]
}

TT_SMI_WORMHOLE_T3K = {
    "device_info": [
        {
            "board_info": {"board_type": "n150", "bus_id": f"0000:0{i}:00.0"},
            "telemetry": {"ASIC_TEMPERATURE": 55.0 + i, "INPUT_POWER": 80.0},
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
    """Patch subprocess.run to return a 2-chip P300C tt-smi snapshot."""
    import subprocess
    result = subprocess.CompletedProcess(
        args=["tt-smi", "-s"], returncode=0,
        stdout=json.dumps(TT_SMI_SINGLE_BH), stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: result)
    return TT_SMI_SINGLE_BH


@pytest.fixture
def smi_t3k(monkeypatch):
    import subprocess
    result = subprocess.CompletedProcess(
        args=["tt-smi", "-s"], returncode=0,
        stdout=json.dumps(TT_SMI_WORMHOLE_T3K), stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: result)
    return TT_SMI_WORMHOLE_T3K
