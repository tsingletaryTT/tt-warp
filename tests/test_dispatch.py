import pytest
from unittest.mock import patch, MagicMock
from tt_mcp.dispatch import dispatch_workload, DispatchResult


@patch("tt_mcp.dispatch.shutil.which", return_value="/usr/local/bin/tt-ctl")
@patch("tt_mcp.dispatch.subprocess.run")
def test_uses_tt_ctl_when_present(mock_run, mock_which):
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    result = dispatch_workload(prompt="a dog in a field", model="wan2.2")
    assert result.method == "tt-ctl"
    assert result.success


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._run_py_path", return_value=None)
@patch("tt_mcp.dispatch.subprocess.run")
def test_falls_back_to_docker_when_no_tt_ctl(mock_run, mock_run_py, mock_which):
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


# ---------------------------------------------------------------------------
# QB2: pre-installed tt-inference-server run.py launcher
# ---------------------------------------------------------------------------

from pathlib import Path
from tt_mcp.dispatch import _tt_device_for


@pytest.mark.parametrize("model,expected", [
    ("Llama-3.3-70B-Instruct", "p300x2"),
    ("Llama-3.1-70B-Instruct", "p300x2"),
    ("Qwen3-32B", "p300x2"),
    ("Qwen3-0.6B", "p100"),
    ("Llama-3.1-8B-Instruct", "p100"),
    (None, "p100"),
])
def test_tt_device_sizing(model, expected):
    """Big models (70B/32B) need the whole box (p300x2); small models fit one
    Blackhole chip (p100)."""
    assert _tt_device_for(model) == expected


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._run_py_path", return_value=Path("/home/u/.local/lib/tt-inference-server/run.py"))
@patch("tt_mcp.dispatch.subprocess.Popen")
def test_prefers_run_py_over_docker(mock_popen, mock_run_py, mock_which):
    """When tt-ctl is absent but the pre-installed run.py exists, dispatch uses
    it (above the raw-docker tier) and returns the child PID."""
    mock_popen.return_value = MagicMock(pid=4242)
    result = dispatch_workload(model="Qwen3-32B")
    assert result.method == "inference-server"
    assert result.success
    assert result.pid == 4242
    # Command must invoke run.py with the right device and server workflow.
    argv = mock_popen.call_args[0][0]
    assert any("run.py" in str(a) for a in argv)
    assert "--tt-device" in argv and "p300x2" in argv
    assert "--workflow" in argv and "server" in argv


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._run_py_path", return_value=Path("/x/run.py"))
@patch("tt_mcp.dispatch.subprocess.Popen")
def test_run_py_pre_occupy_and_release(mock_popen, mock_run_py, mock_which):
    mock_popen.return_value = MagicMock(pid=1)
    llm_state = MagicMock()
    dispatch_workload(model="Qwen3-0.6B", llm_state=llm_state)
    llm_state.pre_occupy.assert_called_once()


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._docker_image_available", return_value=False)
@patch("tt_mcp.dispatch._metal_installed", return_value=False)
def test_returns_setup_needed_when_nothing_found(mock_metal, mock_docker, mock_which):
    result = dispatch_workload(script="run.py")
    assert result.method == "none"
    assert not result.success
    assert "tt-setup" in result.message


@patch("tt_mcp.dispatch.shutil.which", return_value="/usr/local/bin/tt-ctl")
@patch("tt_mcp.dispatch.subprocess.run")
def test_llm_state_pre_occupy_and_released_on_tt_ctl(mock_run, mock_which):
    """llm_state.pre_occupy() and .hardware_released() must each be called
    exactly once on a successful tt-ctl dispatch."""
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    llm_state = MagicMock()
    dispatch_workload(prompt="test", model="wan2.2", llm_state=llm_state)
    llm_state.pre_occupy.assert_called_once()
    llm_state.hardware_released.assert_called_once()


@patch("tt_mcp.dispatch.shutil.which", return_value="/usr/local/bin/tt-ctl")
@patch("tt_mcp.dispatch.subprocess.run", side_effect=Exception("tt-ctl crashed"))
def test_llm_state_released_on_tt_ctl_exception(mock_run, mock_which):
    """hardware_released() must still be called when tt-ctl raises an
    exception, ensuring hardware_busy is never permanently stuck True."""
    llm_state = MagicMock()
    result = dispatch_workload(prompt="test", model="wan2.2", llm_state=llm_state)
    assert not result.success
    llm_state.hardware_released.assert_called_once()


@patch("tt_mcp.dispatch.shutil.which", return_value=None)
@patch("tt_mcp.dispatch._docker_image_available", return_value=False)
@patch("tt_mcp.dispatch._metal_installed", return_value=True)
@patch("tt_mcp.dispatch.subprocess.Popen")
def test_direct_dispatch_when_metal_installed(mock_popen, mock_metal, mock_docker, mock_which):
    """When tt-ctl and Docker are absent but tt-metal is installed, the
    dispatch should use the direct path and return the child PID."""
    mock_popen.return_value = MagicMock(pid=12345)
    result = dispatch_workload(script="my_script.py")
    assert result.method == "direct"
    assert result.success
    assert result.pid == 12345
