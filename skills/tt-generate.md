<!-- skills/tt-generate.md -->
---
name: tt-generate
description: Use when the user expresses intent to generate video, images, or run inference (e.g. "generate a video of X", "run inference on Y", "create an image of Z").
---

# TT Generate

## When to use
Any generative intent: text-to-video, text-to-image, LLM inference, model serving.

## Steps

1. Call `tt_status()`. Check `hardware` for available devices and `llm["hardware_busy"]`.
   - If `hardware_busy: true`, inform the user that hardware is loading and the CPU sidecar (`llm["fallback_url"]`) is handling reasoning in the meantime.
2. Call `tt_knowledge("generate <type> on <mesh_device>")` to find the right model and service for this hardware.
3. If a server is needed and not running: call `tt_serve(model)`. Note the `fallback_llm` in the response — the hardware is now occupied and you should continue using that endpoint.
4. Once a server is needed, poll `tt_status()` — up to 10 times with ~15 seconds between calls — until `llm["active_url"]` matches a healthy endpoint. If the server never comes up after ~150 seconds, call `tt_logs()` for diagnostic output and report the failure to the user. Then call `tt_generate(prompt, model)`.
5. Report progress. If `tt-ctl` is available, call `tt_logs()` to stream output.

## Hardware → model mapping (verify with tt_knowledge)
- P300C / P150X4 → wan2.2, mochi, flux
- N300 / T3K → llama3-8b, llama3-70b (vLLM)
- N150 (single) → llama3-8b (reduced context)
