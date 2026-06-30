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

## Never hardcode — always call tt_knowledge
Architecture details, memory specs, and workload compatibility change with firmware and software versions. Always retrieve from the corpus rather than stating from memory.
