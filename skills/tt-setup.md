<!-- skills/tt-setup.md -->
---
name: tt-setup
description: Use when tt_doctor() reports missing components, or when the user has no TT runtime installed and wants to get started.
---

# TT Setup Guide

## When to use
- `tt_doctor()` returns `tt_smi_available: false`
- `tt_doctor()` shows no hardware detected
- Dispatch returns `method: none` (nothing found)
- User asks "how do I get started with TT hardware"

## Steps

1. Call `tt_doctor()` to inventory what's missing.

2. **If tt-smi not found:**
   Call `tt_knowledge("install tt-smi tt-installer")` for current install command.
   The canonical one-liner is tt-installer: fetch from tenstorrent/tt-installer.
   Tell the user to run it and then restart their shell.

3. **If hugepages not configured:**
   Call `tt_knowledge("hugepages configuration <mesh_device>")` for the correct value for this hardware.
   Apply the returned sysctl command (typically `sudo sysctl -w vm.nr_hugepages=<N>` where N depends on hardware).
   Persist: `echo 'vm.nr_hugepages=<N>' | sudo tee -a /etc/sysctl.conf`

4. **If no runtime for inference (wan2.2 / llama3 etc.):**
   Call `tt_knowledge("tt-inference-server install <mesh_device>")` for the
   Docker pull + run command appropriate to their hardware.

5. **If no TT environment for development:**
   Call `tt_knowledge("setup tt-metal environment")` or
   `tt_knowledge("setup tt-forge environment")` depending on the task.

6. After each step, call `tt_doctor()` again and report what changed.
   Guide incrementally — don't overwhelm with all steps at once.
