import os
import pytest
from tt_mcp.envs import detect_active_env, get_activation_snippet, ENVIRONMENTS


def test_detect_metal_via_virtual_env(monkeypatch, tmp_path):
    venv = tmp_path / "tt-metal" / "python_env"
    venv.mkdir(parents=True)
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    assert detect_active_env() == "metal"


def test_detect_forge_via_virtual_env(monkeypatch, tmp_path):
    venv = tmp_path / "tt-forge-venv"
    venv.mkdir(parents=True)
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    assert detect_active_env() == "forge"


def test_detect_none_when_no_venv(monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("TT_METAL_HOME", raising=False)
    assert detect_active_env() is None


def test_activation_snippet_forge_unsets_tt_metal_home():
    snippet = get_activation_snippet("forge")
    assert "unset TT_METAL_HOME" in snippet
    assert "tt-forge-venv" in snippet


def test_activation_snippet_metal_sets_tt_metal_home():
    snippet = get_activation_snippet("metal")
    assert "TT_METAL_HOME" in snippet
    assert "tt-metal/python_env" in snippet


def test_activation_snippet_unknown_raises():
    with pytest.raises(KeyError):
        get_activation_snippet("nonexistent")
