---
name: tt-connect-ui
description: Use when the user wants to connect a chat UI or client to their local TT model (e.g. "open a chat window", "use Open WebUI", "point my editor at the local model", "I used to use Ollama").
---

# Connect a Chat UI to a Local TT Model

The TT inference server exposes an OpenAI-compatible API on `:8000`. Any client
that talks to OpenAI works by changing the base URL — no code changes, no
provider lock-in.

## When to use
- User wants a browser chat window in front of their served model
- User mentions Open WebUI, LibreChat, Continue.dev, or "a frontend"
- User is "coming from Ollama" and wants the same experience
- User wants to reach the model from a laptop / another machine

## Prerequisite

A model must be serving on `:8000`. Call `tt_status()` and check `llm.primary_url`
— if it's null, transition to the **tt-serve-llm** skill first. (Ollama itself
does not run on Blackhole; point Ollama-style tools at `:8000` instead.)

## Steps

1. Confirm the endpoint:
   ```bash
   curl -s http://localhost:8000/v1/models | python3 -m json.tool
   ```
2. Launch Open WebUI (the common default), pointed at the local server:
   ```bash
   docker run -d --network=host \
     -e OPENAI_API_BASE_URL=http://localhost:8000/v1 \
     -e OPENAI_API_KEY=not-checked \
     -v open-webui:/app/backend/data \
     --name open-webui ghcr.io/open-webui/open-webui:main
   ```
   Open `http://localhost:8080`; the served model appears in its picker.
3. For other clients, the same `:8000/v1` endpoint drives them all:
   - **LibreChat** — multi-model chat UI with history/presets (Docker, browser)
   - **Continue.dev** — in-editor assistant for VS Code / JetBrains; set its API
     base to `http://localhost:8000/v1`
   - Any OpenAI SDK: `base_url="http://localhost:8000/v1"`, `api_key` = any
     non-empty string (the server ignores it).

## Remote access (laptop → the TT box)

The server listens on localhost. To reach it from another machine, forward the
port over SSH rather than widening the firewall:
```bash
ssh -L 8000:localhost:8000 <user>@<tt-host>
# then on the laptop: curl http://localhost:8000/v1/models
```
Do not expose `:8000` to the internet unauthenticated — the API trusts any
caller. For shared use, put an authenticating reverse proxy in front of it.
