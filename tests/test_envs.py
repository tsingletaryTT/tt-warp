import os
import pytest
import tt_mcp.envs as envs_mod
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


# ---------------------------------------------------------------------------
# QB2 / Blackhole support
# ---------------------------------------------------------------------------

def test_vllm_uses_tenstorrent_venv_on_qb2(monkeypatch, tmp_path):
    """On a QB2 the vLLM venv is ~/.tenstorrent-venv, not the tt-metal build
    tree, and TT_METAL_HOME must NOT be pointed at the source-less ~/tt-metal."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".tenstorrent-venv").mkdir()
    snippet = get_activation_snippet("vllm")
    assert ".tenstorrent-venv" in snippet
    assert "python_env_vllm" not in snippet
    assert "TT_METAL_HOME" not in snippet


def test_vllm_falls_back_to_metal_build_venv(monkeypatch, tmp_path):
    """Without ~/.tenstorrent-venv (a tt-metal build machine), vLLM resolves to
    the build tree venv and sets TT_METAL_HOME as before."""
    monkeypatch.setenv("HOME", str(tmp_path))  # no .tenstorrent-venv created
    snippet = get_activation_snippet("vllm")
    assert "python_env_vllm" in snippet
    assert "TT_METAL_HOME" in snippet


def test_metal_snippet_sets_arch_name(monkeypatch):
    """Metal-backed envs must export TT_METAL_ARCH_NAME for the detected arch."""
    snippet = get_activation_snippet("metal", arch="blackhole")
    assert 'TT_METAL_ARCH_NAME="blackhole"' in snippet


def test_vllm_snippet_sets_arch_name(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    snippet = get_activation_snippet("vllm", arch="blackhole")
    assert 'TT_METAL_ARCH_NAME="blackhole"' in snippet


def test_arch_autodetected_when_not_passed(monkeypatch):
    """When arch is not passed, it is auto-detected from hardware."""
    monkeypatch.setattr(envs_mod, "_detected_arch", lambda: "wormhole")
    snippet = get_activation_snippet("metal")
    assert 'TT_METAL_ARCH_NAME="wormhole"' in snippet


def test_no_arch_line_when_undetectable(monkeypatch):
    """No arch line is emitted when hardware arch can't be determined."""
    monkeypatch.setattr(envs_mod, "_detected_arch", lambda: None)
    snippet = get_activation_snippet("metal")
    assert "TT_METAL_ARCH_NAME" not in snippet


def test_forge_snippet_has_no_arch_line(monkeypatch):
    """forge is not a Metal-backed env; it must not get the arch flag."""
    monkeypatch.setattr(envs_mod, "_detected_arch", lambda: "blackhole")
    snippet = get_activation_snippet("forge")
    assert "TT_METAL_ARCH_NAME" not in snippet


def test_detect_active_env_tenstorrent_venv(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/home/x/.tenstorrent-venv")
    assert detect_active_env() == "vllm"
