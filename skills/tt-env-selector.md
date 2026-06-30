---
name: tt-env-selector
description: Use when the user asks which TT environment to activate, or when an environment error is detected in the terminal output.
---

# TT Environment Selector

## When to use
- User asks "which environment do I need for X"
- User gets ImportError or missing-module error in a TT workload
- User wants to switch between tt-metal, tt-forge, tt-vllm, tt-xla

## Steps

1. Call `tt_status()` to see the currently active environment.
2. Call `tt_knowledge("which environment for <task>")` to look up the right env. Always include the task (e.g. "model training", "vLLM inference", "forge compilation").
3. Call `tt_activate_env(name)` with the correct env name. Return the `snippet` field to the user and tell them to run it, or eval it directly if the shell hook is active.
4. If `tt_activate_env` returns `success: false`, call `tt_doctor()` to check whether the env is installed at all. If not, transition to the tt-setup skill.

## Key env facts (delegate details to tt_knowledge)
- `forge` requires unsetting TT_METAL_HOME — do not skip this
- `vllm` and `metal` share the same TT_METAL_HOME but different venvs
- Never mix envs in one shell session without deactivating first
