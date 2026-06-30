---
name: tt-crash-diagnoser
description: Use when error output, a crash, or a hang appears in the terminal from a TT workload.
---

# TT Crash Diagnoser

## When to use
- Python traceback containing tt_metal, ttnn, or TT-specific paths
- "NOC timeout", "hugepage", "undefined symbol", or shared memory errors
- Process hangs with no output

## Steps

1. Collect the full error output — include at least the last 50 lines.
2. Call `tt_diagnose(log_text)` with the collected text.
3. For each item in the `diagnoses` list returned:
   a. Present `item["summary"]` and `item["remediation"]` to the user clearly.
   b. Call `tt_knowledge(item["category"])` to find related lessons or additional context.
4. If `tt_diagnose` returns no results, call `tt_doctor()` to check system health broadly.
5. After remediation, suggest re-running the workload and watching for the same error.

## Common patterns
- `wrong_venv` → switch environment; use tt-env-selector skill
- `hugepages` → one-line sysctl fix; may need sudo
- `shm` → clear /dev/shm/tenstorrent* + tt-smi -r
- `noc_timeout` → reset devices, check for stale processes
