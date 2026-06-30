from tt_mcp.diag import parse_log, Diagnosis


def test_detects_hugepage_failure():
    log = "RuntimeError: Failed to mmap hugepage. Check /proc/sys/vm/nr_hugepages"
    results = parse_log(log)
    assert any(d.category == "hugepages" for d in results)
    diag = next(d for d in results if d.category == "hugepages")
    assert "nr_hugepages" in diag.remediation.lower() or "hugepage" in diag.remediation.lower()


def test_detects_shm_exhaustion():
    log = "OSError: [Errno 28] No space left on device: '/dev/shm/tenstorrent'"
    results = parse_log(log)
    assert any(d.category == "shm" for d in results)


def test_detects_wrong_venv_symbol_error():
    log = "ImportError: /home/user/tt-vllm/vllm/_C.abi3.so: undefined symbol: _ZN5torch"
    results = parse_log(log)
    assert any(d.category == "wrong_venv" for d in results)
    diag = next(d for d in results if d.category == "wrong_venv")
    assert "env" in diag.remediation.lower()


def test_detects_noc_timeout():
    log = "tt::tt_metal::detail::RuntimeAssertException: NOC timeout detected on chip 0"
    results = parse_log(log)
    assert any(d.category == "noc_timeout" for d in results)


def test_detects_driver_version_mismatch():
    log = "Exception: Driver version 1.2 does not match firmware version 1.3"
    results = parse_log(log)
    assert any(d.category == "driver_mismatch" for d in results)


def test_clean_log_returns_empty():
    assert parse_log("Model loaded successfully. Running inference.") == []


# ---------------------------------------------------------------------------
# QB2 / Blackhole error patterns
# ---------------------------------------------------------------------------

def test_detects_dispatch_core_axis():
    log = "RuntimeError: DispatchCoreAxis.ROW is not supported on this device"
    results = parse_log(log)
    d = next(d for d in results if d.category == "dispatch_core")
    assert "WORKER" in d.remediation


def test_detects_gated_repo():
    log = ("huggingface_hub.errors.GatedRepoError: Access to model "
           "meta-llama/Llama-3.3-70B-Instruct is restricted.")
    results = parse_log(log)
    d = next(d for d in results if d.category == "gated_repo")
    assert "HF_TOKEN" in d.remediation or "license" in d.remediation.lower()


def test_detects_device_enumeration():
    log = "Opening device 2... FAILED. Only 2 of 4 Tenstorrent devices available."
    results = parse_log(log)
    d = next(d for d in results if d.category == "device_enumeration")
    assert "modprobe" in d.remediation


def test_detects_hugepages_1g_mount():
    log = ('Error response from daemon: invalid mount config for type "bind": '
           'source /dev/hugepages-1G does not exist')
    results = parse_log(log)
    assert any(d.category == "hugepages_1g" for d in results)
