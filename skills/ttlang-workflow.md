<!-- skills/ttlang-workflow.md -->
---
name: ttlang-workflow
description: Use when the user is working in a tt-lang directory, mentions kernel development, or wants to write/run a custom TT kernel.
---

# TT-Lang Workflow

## When to use
- User mentions tt-lang, TT-Metal kernels, NOC operations, custom ops
- Working directory contains tt-lang project markers (pyproject.toml with tt-lang dep, *.ttlang files)
- User wants to translate a CUDA/Triton kernel to TT hardware

## Workflow: sim → compile → hardware

1. **Simulate first (no hardware needed)**
   - Check `build/env/activate` exists; if not, guide user to build with `-DTTLANG_SIM_ONLY=ON`
   - Run: `source build/env/activate && ttlang-sim <kernel.py>`
   - Simulation catches logic errors without burning hardware time

2. **Compile for hardware**
   - Use the `dist` Docker image: `ghcr.io/tenstorrent/tt-lang/tt-lang-dist-ubuntu-22-04:latest`
   - Call `tt_knowledge("tt-lang compile hardware")` for current Docker run command
   - Never try to compile inside the `dist` container (no build toolchain)

3. **Run on hardware**
   - Call `tt_status()` to confirm device availability
   - Ensure correct env: `tt_activate_env("metal")`
   - Find the running container: `docker ps --filter ancestor=ghcr.io/tenstorrent/tt-lang/tt-lang-dist-ubuntu-22-04:latest --format '{{.Names}}'`
   - Run: `docker exec <container_name> python <kernel.py>`

4. **Debug**: call `tt_diagnose(log)` on any crash output before attempting fixes.
