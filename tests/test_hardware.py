"""Tests for tt_mcp.hardware — hardware detection via tt-smi.

All subprocess calls are monkeypatched in conftest.py fixtures; no real
hardware or tt-smi binary is required to run this test suite.
"""

import pytest
from tt_mcp.hardware import detect_hardware, get_mesh_device, is_blackhole


def test_detect_hardware_p300c(smi_p300c):
    """Two-chip P300C snapshot: count == 2, primary_type == 'P300C'."""
    hw = detect_hardware()
    assert hw is not None
    assert hw["count"] == 2
    assert hw["primary_type"] == "P300C"
    assert hw["devices"][0]["temperature"] == pytest.approx(65.5)
    assert hw["devices"][0]["firmware"] == "80.15.0.0"


def test_detect_hardware_t3k(smi_t3k):
    """Eight-chip T3K snapshot: count == 8, primary_type == 'N300'."""
    hw = detect_hardware()
    assert hw["count"] == 8
    assert hw["primary_type"] == "N300"


def test_detect_hardware_no_smi(monkeypatch):
    """When tt-smi is not on PATH, detect_hardware() returns None."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert detect_hardware() is None


def test_mesh_device_p300c_two_chips(smi_p300c):
    """Two P300C chips → mesh device name is 'P300'."""
    assert get_mesh_device() == "P300"


def test_mesh_device_t3k(smi_t3k):
    """Eight N300 chips (4× dual-chip boards) → mesh device name is 'T3K'."""
    assert get_mesh_device() == "T3K"


def test_is_blackhole_p300c(smi_p300c):
    """P300C is a Blackhole-architecture board → is_blackhole() is True."""
    assert is_blackhole() is True


def test_is_blackhole_wormhole(smi_t3k):
    """N300 is a Wormhole-architecture board → is_blackhole() is False."""
    assert is_blackhole() is False
