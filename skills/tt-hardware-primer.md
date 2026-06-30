---
name: tt-hardware-primer
description: Use when the user asks about their hardware, chip topology, device names, or "what hardware do I have".
---

# TT Hardware Primer

## When to use
- "What hardware do I have?"
- Questions about Blackhole vs Wormhole, chip count, mesh topology
- Questions about device naming (P150X4, T3K, N300, etc.)

## Steps

1. Call `tt_list_devices()` to enumerate actual connected devices.
2. Call `tt_status()` for `mesh_device` — the normalized name for software.
3. Call `tt_knowledge("hardware architecture <primary_type>")` for context-appropriate explanation.
4. Present: device count, board type, mesh device name, architecture generation, and what workloads it's suited for.

## QB2 / Blackhole topology — get this right
A QuietBox 2 (QB2) is **2× Blackhole p300c cards = 4 Blackhole chips**, which
the software sees as **4 independent PCIe devices, not a mesh**:
- There is **no inter-chip Ethernet** between QB2 chips (unlike T3K or Galaxy);
  the chips do not share memory. `mesh_device` is a normalized label, not a
  claim that the chips are wired into a fabric.
- Multi-device work opens all four together with `ttnn.CreateDevices({0,1,2,3})`
  / `ttnn.CloseDevices` — not four separate `open_device()` calls.
- Blackhole ≠ Wormhole: different APIs and a different arch flag apply. Anything
  tt-metal-backed needs `TT_METAL_ARCH_NAME=blackhole` (the tt-env-selector
  skill sets this automatically).
- A QB2 ships **without a tt-metal source tree** — `~/tt-metal` holds venvs, not
  source. vLLM lives in `~/.tenstorrent-venv`.

## Never hardcode — always call tt_knowledge
Architecture details, memory specs, and workload compatibility change with firmware and software versions. Always retrieve from the corpus rather than stating from memory.
