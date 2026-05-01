import shutil
from unittest.mock import patch, MagicMock
import pytest
from tt_mcp.dispatch import dispatch_workload, DispatchResult


@patch("tt_mcp.dispatch.shutil.which", return_value="/usr/local/bin/tt-ctl")
@patch("tt_mcp.dispatch.subprocess.run")
def test_uses_tt_ctl_when_present(mock_run, mock_which):
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    result = dispatch_workload(prompt="a dog in a field", model="wan2.2")
    assert result.method == "tt-ctl"
    assert result.success


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch.subprocess.run")
def test_falls_back_to_docker_when_no_tt_ctl(mock_run, mock_which):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="ghcr.io/tenstorrent/tt-inference-server  latest  abc123",
        stderr="",
    )
    with patch("tt_mcp.dispatch._docker_image_available", return_value=True):
        with patch("tt_mcp.dispatch._launch_docker") as mock_docker:
            mock_docker.return_value = DispatchResult(
                method="docker", success=True, message="started"
            )
            result = dispatch_workload(prompt="a dog", model="wan2.2")
            assert result.method == "docker"


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._docker_image_available", return_value=False)
@patch("tt_mcp.dispatch._metal_installed", return_value=False)
def test_returns_setup_needed_when_nothing_found(mock_metal, mock_docker, mock_which):
    result = dispatch_workload(script="run.py")
    assert result.method == "none"
    assert not result.success
    assert "tt-setup" in result.message
