---
name: tt-serve-llm
description: Use when the user wants to serve, deploy, or run an LLM locally on TT hardware (e.g. "serve Llama on my box", "run a model", "start an inference server", "deploy Qwen3").
---

# Serve an LLM on TT Hardware

Bring up a local, OpenAI-compatible inference server on the user's Tenstorrent
hardware. On a QB2 this routes through the pre-installed `tt-inference-server`
`run.py` launcher, which sizes the deployment to the model and exposes the API
on `:8000`.

## When to use
- User says "serve / deploy / run <model>", "start an inference server", or
  "I want to chat with a local model"
- User asks which model to run, or how big a model their hardware can handle
- User wants an OpenAI-compatible endpoint on their own silicon

## Pick the model first

If the user hasn't named a model, recommend based on intent. Confirm hardware
with `tt_status()` first, then call `tt_knowledge("model zoo <board>")` for the
authoritative list. General guidance for a QB2 (2× p300c = 4 Blackhole chips):

| Goal | Model | Device |
|------|-------|--------|
| **Best default — capable + zero download** | **Qwen3-32B** (pre-cached on disk) | `p300x2` (all 4 chips) |
| Maximum quality | Llama-3.3-70B-Instruct | `p300x2` |
| Reasoning (no license gate) | DeepSeek-R1-Distill-Llama-70B | `p300x2` |
| Single-chip production | Llama-3.1-8B-Instruct / Qwen3-8B | `p100` (1 chip) |
| Smoke test | Qwen3-0.6B | `p100` |

Key facts to apply:
- **Qwen3-32B ships pre-cached** on a QB2 — no download, no HF license gate, and
  it's the strongest "just works right now" option. Recommend it as the default.
- 70B/32B-class models need the whole box; ≤14B fit one chip. `tt_serve` sizes
  `--tt-device` automatically (`p300x2` for 70B/32B, else `p100`).
- The QB2 ceiling is ~70B. Larger needs an 8-chip box (T3K / LoudBox); say so
  rather than attempting it.
- Gated weights (Meta Llama) need `HF_TOKEN` and an accepted license. If the
  user hits a `GatedRepoError`, run `tt_diagnose()` on the log.

## Steps

1. Call `tt_doctor()` to confirm hardware, hugepages, and a clean device state.
   If anything is missing, transition to the **tt-setup** skill before serving.
2. Call `tt_serve(model)` with the chosen model name. This dispatches through
   tt-ctl → the pre-installed `run.py` → cached Docker image, and returns a
   `method`, `success`, `message`, and `fallback_llm`.
3. Tell the user the server is warming up. **First run compiles weights
   (~3–5 min, longer if downloading)** — surface the `fallback_llm` URL so the
   agent stays responsive during the load (beer handoff).
4. Poll readiness, then verify:
   ```bash
   curl -s http://localhost:8000/v1/models | python3 -m json.tool
   ```
   When the model appears, the OpenAI-compatible API on `:8000` is live.
5. To put a UI or client in front of it, transition to the **tt-connect-ui**
   skill.

## If serving fails
- Run `tt_diagnose()` on the server log first — it recognises gated-repo,
  1G-hugepages-mount, device-enumeration, and dispatch-core errors with fixes.
- `tt_serve` returning `method: "none"` means no runtime was found → tt-setup.
