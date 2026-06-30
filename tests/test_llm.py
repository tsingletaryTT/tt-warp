import pytest
import responses as rsps_lib
from tt_mcp.llm import probe_endpoints, LLMState, CANDIDATE_PORTS


@rsps_lib.activate
def test_probe_finds_tt_inference_server():
    rsps_lib.add(rsps_lib.GET, "http://localhost:8000/v1/models",
                 json={"data": [{"id": "llama3-8b"}]}, status=200)
    state = probe_endpoints()
    assert state.primary_url == "http://localhost:8000"
    assert state.primary_model == "llama3-8b"
    assert not state.hardware_busy


@rsps_lib.activate
def test_probe_finds_sidecar_only():
    rsps_lib.add(rsps_lib.GET, "http://localhost:8001/v1/models",
                 json={"data": [{"id": "Qwen3-0.6B"}]}, status=200)
    state = probe_endpoints()
    assert state.primary_url is None
    assert state.fallback_url == "http://localhost:8001"


def test_sidecar_port_8011_is_a_candidate():
    """tt-warp's own CPU sidecar runs on :8011 (off QB2's :8001 prompt
    server), so 8011 must be in the probe list as a sidecar role."""
    assert (8011, "sidecar") in CANDIDATE_PORTS


@rsps_lib.activate
def test_probe_finds_tt_warp_sidecar_on_8011():
    rsps_lib.add(rsps_lib.GET, "http://localhost:8011/v1/models",
                 json={"data": [{"id": "Qwen3-0.6B"}]}, status=200)
    state = probe_endpoints()
    assert state.fallback_url == "http://localhost:8011"


@rsps_lib.activate
def test_probe_finds_nothing():
    state = probe_endpoints()
    assert state.primary_url is None
    assert state.fallback_url is None
    assert state.active_url is None


@rsps_lib.activate
def test_pre_occupy_sets_busy_flag():
    rsps_lib.add(rsps_lib.GET, "http://localhost:8000/v1/models",
                 json={"data": [{"id": "llama3-8b"}]}, status=200)
    rsps_lib.add(rsps_lib.GET, "http://localhost:8001/v1/models",
                 json={"data": [{"id": "Qwen3-0.6B"}]}, status=200)
    state = probe_endpoints()
    state.pre_occupy()
    assert state.hardware_busy
    assert state.active_url == "http://localhost:8001"


@rsps_lib.activate
def test_hardware_released_clears_busy():
    rsps_lib.add(rsps_lib.GET, "http://localhost:8000/v1/models",
                 json={"data": [{"id": "llama3-8b"}]}, status=200)
    rsps_lib.add(rsps_lib.GET, "http://localhost:8001/v1/models",
                 json={"data": [{"id": "Qwen3-0.6B"}]}, status=200)
    state = probe_endpoints()
    state.pre_occupy()
    state.hardware_released()
    assert not state.hardware_busy
    assert state.active_url == "http://localhost:8000"
