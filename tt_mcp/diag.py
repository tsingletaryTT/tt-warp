"""
tt_mcp/diag.py — TT-specific error log parser with structured remediation.

Called by the MCP server when an agent passes in crash output (stdout/stderr).
Returns a list of Diagnosis objects, each with a category, human-readable
summary, actionable remediation steps, and a severity level.

Usage:
    from tt_mcp.diag import parse_log, Diagnosis

    diagnoses = parse_log(log_text)
    for d in diagnoses:
        print(d.category, d.severity)
        print(d.summary)
        print(d.remediation)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Diagnosis:
    """A single matched error pattern with structured remediation info.

    Attributes:
        category:    Short machine-readable label (e.g. "hugepages", "shm").
        summary:     One-line human-readable description of the problem.
        remediation: Multi-line, copy-pasteable steps to fix the problem.
        severity:    Either "error" (blocks execution) or "warning" (degrades
                     performance / may cause later failures).
    """

    category: str
    summary: str
    remediation: str
    severity: str  # "error" | "warning"


# ---------------------------------------------------------------------------
# Pattern registry
# Each entry is a 5-tuple:
#   (category, severity, regex_pattern, summary, remediation)
#
# Patterns are matched with re.IGNORECASE against the full log text.
# The first matching pattern wins nothing — ALL matching patterns are returned
# so a single log can yield multiple diagnoses.
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, str, str, str, str]] = [
    # -----------------------------------------------------------------------
    # HugePage allocation failure
    # Triggered when tt-metal cannot mmap a hugepage-backed buffer, usually
    # because the kernel huge-page pool is empty.
    # -----------------------------------------------------------------------
    (
        "hugepages",
        "error",
        r"hugepage|nr_hugepages|mmap.*hugepage",
        "HugePage allocation failed",
        "Run: sudo sysctl -w vm.nr_hugepages=1024\n"
        "To persist: echo 'vm.nr_hugepages=1024' | sudo tee -a /etc/sysctl.conf",
    ),
    # -----------------------------------------------------------------------
    # /dev/shm exhaustion
    # Tenstorrent device drivers write shared-memory files under
    # /dev/shm/tenstorrent/.  If a previous run crashed without cleanup,
    # stale files accumulate and fill the tmpfs mount.
    # -----------------------------------------------------------------------
    (
        "shm",
        "error",
        r"/dev/shm/tenstorrent|No space left.*shm",
        "Shared memory exhausted",
        "Clear stale TT shared memory: sudo rm -f /dev/shm/tenstorrent*\n"
        "Then reset devices: tt-smi -r",
    ),
    # -----------------------------------------------------------------------
    # Wrong Python environment / ABI mismatch
    # The .abi3.so C extension was compiled against a different PyTorch ABI
    # than the one found at runtime.  Almost always means the user activated
    # a venv that doesn't match the workload (e.g. running vLLM ops inside
    # the base tt-metal env).
    # -----------------------------------------------------------------------
    (
        "wrong_venv",
        "error",
        r"undefined symbol.*torch|abi3\.so.*undefined|ImportError.*_C\.abi3",
        "C extension symbol error — likely wrong Python environment",
        "Activate the correct environment for this workload.\n"
        "For vLLM: source ~/tt-metal/build/python_env_vllm/bin/activate\n"
        "For direct tt-metal: source ~/tt-metal/python_env/bin/activate",
    ),
    # -----------------------------------------------------------------------
    # NOC (Network-on-Chip) timeout
    # Indicates the on-chip router did not receive an acknowledgement within
    # the expected window.  Can be caused by a hung kernel, bad firmware, or
    # a physical device issue.
    # -----------------------------------------------------------------------
    (
        "noc_timeout",
        "error",
        r"noc.*timeout",
        "NOC (Network-on-Chip) timeout on TT device",
        "Reset devices: tt-smi -r\n"
        "If persistent, check for stale processes: pkill -9 -f tt-metal",
    ),
    # -----------------------------------------------------------------------
    # Driver / firmware version mismatch
    # The kernel driver version reported by the OS does not match the firmware
    # burned onto the device.  Typically resolved by reflashing firmware or
    # reinstalling the driver package.
    # -----------------------------------------------------------------------
    (
        "driver_mismatch",
        "error",
        r"driver version.*does not match|firmware.*mismatch|tenstorrent.*version mismatch",
        "Driver/firmware version mismatch",
        "Update firmware: tt-smi --update-firmware\n"
        "Or reinstall drivers via tt-installer: "
        "https://github.com/tenstorrent/tt-installer",
    ),
    # -----------------------------------------------------------------------
    # Intel Extension for PyTorch conflict (warning-level)
    # intel_extension_for_pytorch is a CPU-only optimisation package and
    # conflicts with Tenstorrent's PyTorch backend.  It shouldn't be present
    # in any TT environment.
    # -----------------------------------------------------------------------
    (
        "intel_extension",
        "warning",
        r"Intel.*Extension.*PyTorch|intel_extension_for_pytorch",
        "Intel Extension for PyTorch conflict (CPU-only package, not needed for TT)",
        "Remove it: pip uninstall intel_extension_for_pytorch",
    ),
    # -----------------------------------------------------------------------
    # Wrong dispatch-core configuration (Blackhole / QB2)
    # Code written for an older default trips DispatchCoreAxis.ROW; Blackhole
    # wants the WORKER dispatch core type.
    # -----------------------------------------------------------------------
    (
        "dispatch_core",
        "error",
        r"DispatchCoreAxis\.ROW|dispatch.?core.*axis",
        "Wrong dispatch-core configuration for this device",
        "Use the WORKER dispatch core type:\n"
        "  ttnn.DispatchCoreConfig(ttnn.DispatchCoreType.WORKER)",
    ),
    # -----------------------------------------------------------------------
    # Gated Hugging Face repository (e.g. Meta Llama weights)
    # The HF token lacks access, or the model license has not been accepted.
    # -----------------------------------------------------------------------
    (
        "gated_repo",
        "error",
        r"GatedRepoError|Access to model.*restricted|gated repo|cannot access gated",
        "Hugging Face model is gated — token lacks access",
        "Accept the model license on huggingface.co while logged into the same\n"
        "account, then export a read token:\n"
        "  export HF_TOKEN=hf_your_token_here",
    ),
    # -----------------------------------------------------------------------
    # Device enumeration failure
    # tt-smi sees all chips but the runtime/container opens only some.  Usually
    # a stale kernel-mode driver; a reload re-exposes every /dev/tenstorrent/N.
    # -----------------------------------------------------------------------
    (
        "device_enumeration",
        "error",
        r"failed to open device|opening device.*failed|only \d+ of \d+.*device|could not open.*tenstorrent|unable to (open|enumerate) device|/dev/tenstorrent/\d+ not found",
        "Could not open all TT devices (driver may need a reload)",
        "Check the device nodes: ls /dev/tenstorrent/   (expect 0 1 2 3 on QB2)\n"
        "Reload the kernel-mode driver:\n"
        "  sudo rmmod tenstorrent && sudo modprobe tenstorrent",
    ),
    # -----------------------------------------------------------------------
    # 1G hugepages mount missing (Docker bind-mount failure)
    # tt-inference-server bind-mounts /dev/hugepages-1G; if 1G hugepages are
    # not configured the mount source does not exist and Docker refuses to run.
    # -----------------------------------------------------------------------
    (
        "hugepages_1g",
        "error",
        r"hugepages-1G|invalid mount config.*hugepage",
        "1G hugepages mount missing for tt-inference-server",
        "Configure 1G hugepages and the hugetlbfs mount:\n"
        "  echo 'vm.nr_hugepages = 32' | sudo tee /etc/sysctl.d/99-hugepages.conf\n"
        "  sudo sysctl -p /etc/sysctl.d/99-hugepages.conf\n"
        "  sudo mkdir -p /dev/hugepages-1G\n"
        "  sudo mount -t hugetlbfs -o pagesize=1G hugetlbfs /dev/hugepages-1G",
    ),
]


def parse_log(log_text: str) -> list[Diagnosis]:
    """Scan *log_text* for known TT error patterns and return diagnoses.

    Iterates over all registered patterns and collects every match so that a
    single crash log with multiple problems returns multiple Diagnosis objects.
    Returns an empty list when no known patterns are found.

    Args:
        log_text: Raw log output (stdout, stderr, or a combined dump) from a
                  Tenstorrent workload.

    Returns:
        A list of :class:`Diagnosis` instances, one per matched pattern, in
        registration order.  Empty list when the log is clean.
    """
    results: list[Diagnosis] = []

    for category, severity, pattern, summary, remediation in _PATTERNS:
        if re.search(pattern, log_text, re.IGNORECASE):
            results.append(
                Diagnosis(
                    category=category,
                    summary=summary,
                    remediation=remediation,
                    severity=severity,
                )
            )

    return results
