import subprocess
from unittest.mock import MagicMock, patch
import pytest
from tt_mcp.cpu_sidecar import CpuSidecar, find_existing_sidecar, _SIDECAR_PORT


def test_sidecar_port_avoids_inference_server_prompt_server():
    """The CPU sidecar must not bind :8001 — on a QB2 that port is taken by
    tt-inference-server's prompt server. It lives on :8011 instead."""
    assert _SIDECAR_PORT == 8011
    assert CpuSidecar().port == 8011


@patch("tt_mcp.cpu_sidecar.requests.get")
def test_find_existing_sidecar_running(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"data": [{"id": "Qwen3-0.6B"}]}
    url = find_existing_sidecar()
    assert url == "http://localhost:8011"


@patch("tt_mcp.cpu_sidecar.requests.get", side_effect=Exception("refused"))
def test_find_existing_sidecar_none(mock_get):
    assert find_existing_sidecar() is None


def test_sidecar_ensure_running_uses_existing(monkeypatch):
    monkeypatch.setattr("tt_mcp.cpu_sidecar.find_existing_sidecar",
                        lambda: "http://localhost:8011")
    sidecar = CpuSidecar()
    url = sidecar.ensure_running()
    assert url == "http://localhost:8011"
    assert sidecar._proc is None  # did not spawn a new process


def test_sidecar_url_none_when_not_running():
    sidecar = CpuSidecar()
    # On CI, no sidecar is running and no process was spawned
    # Patch find_existing_sidecar to return None
    with patch("tt_mcp.cpu_sidecar.find_existing_sidecar", return_value=None):
        assert sidecar.url is None
