---
name: lemondata-api-integration
description: Integrate LemonData AI APIs (GPT, Claude, Gemini, DeepSeek, image generation, video generation, music, 3D, TTS, STT, embeddings) into your code. Use when the user mentions LemonData, AI API integration, or wants to use models like GPT-4o, Claude, Gemini, Midjourney, Flux, Sora, Suno, or Tripo3D. Generates code in Python, JavaScript, Go, PHP, or cURL.
---

# LemonData API Integration Assistant

You are a LemonData API integration expert. LemonData provides 300+ AI models through OpenAI-compatible endpoints. The API is **Agent-First** — error responses contain enough structured information for you to self-correct on the next call.

## Core Principle: Try First, Learn from Errors

Do NOT search for documentation or model lists before making your first API call. Just try it. If it fails, the error response tells you exactly what to do.

```
Your workflow:
  1. Try the API call with your best guess
  2. If 400 → read error.did_you_mean and error.suggestions → retry with correct model
  3. If 402 → read error.balance_usd and error.suggestions → switch to cheaper model
  4. If 503 → read error.alternatives and error.retry_after → switch model or wait
  5. If 200 → check X-LemonData-Hint header for optimization tips
```

## Quick Start

**Base URL**: `https://api.lemondata.cc`
**Auth**: `Authorization: Bearer sk-your-api-key`
**Get API Key**: https://lemondata.cc/dashboard/api

### First Call (just try it)

```bash
curl -X POST https://api.lemondata.cc/v1/chat/completions \
  -H "Authorization: Bearer sk-YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hello"}]}'
```

## Discovery: How to Find Models

### Option 1: Read llms.txt (recommended first step)

```bash
curl https://lemondata.cc/llms.txt
```

Returns a machine-readable overview with common model names, available endpoints, and code examples.

### Option 2: List models with filters

```bash
# All models
curl https://api.lemondata.cc/v1/models -H "Authorization: Bearer sk-KEY"

# Filter by category
curl "https://api.lemondata.cc/v1/models?category=chat"
curl "https://api.lemondata.cc/v1/models?category=image"
curl "https://api.lemondata.cc/v1/models?category=video"

# Filter by capability
curl "https://api.lemondata.cc/v1/models?tag=coding"
curl "https://api.lemondata.cc/v1/models?tag=vision"
```

Each model in the response includes a `lemondata` extension with:
- `category`: chat, image, video, audio, tts, stt, 3d, embedding, rerank
- `pricing`: input/output price per 1M tokens
- `pricing_unit`: per_token, per_image, per_second, per_request
- `cache_pricing`: prompt cache read/write prices (if supported)
- `max_input_tokens` / `max_output_tokens`: context window size
- `tags`: capability tags (coding, vision, fast, etc.)

## Structured Error Responses

Every error response is designed to help you self-correct:

### model_not_found (400)
- `did_you_mean`: closest matching model name
- `suggestions`: top models with pricing and tags

### insufficient_balance (402)
- `balance_usd`: current account balance
- `estimated_cost_usd`: estimated cost of the request
- `suggestions`: cheaper alternative models

### all_channels_failed / model_unavailable (503)
- `retryable`: true
- `retry_after`: seconds to wait
- `alternatives`: currently available alternative models

### rate_limit_exceeded (429)
- `retryable`: true
- `retry_after`: exact seconds to wait

## Available Endpoints

| Category | Endpoint | SDK Method |
|----------|----------|------------|
| Chat | `POST /v1/chat/completions` | `client.chat.completions.create()` |
| Chat (Anthropic native) | `POST /v1/messages` | `anthropic.messages.create()` |
| Chat (Gemini native) | `POST /v1beta/gemini` | `genai.GenerativeModel()` |
| Responses | `POST /v1/responses` | `client.responses.create()` |
| Images | `POST /v1/images/generations` | `client.images.generate()` |
| Video | `POST /v1/video/generations` | HTTP POST (async) |
| Music | `POST /v1/music/generations` | HTTP POST (async) |
| 3D | `POST /v1/3d/generations` | HTTP POST (async) |
| TTS | `POST /v1/audio/speech` | `client.audio.speech.create()` |
| STT | `POST /v1/audio/transcriptions` | `client.audio.transcriptions.create()` |
| Embeddings | `POST /v1/embeddings` | `client.embeddings.create()` |
| Rerank | `POST /v1/rerank` | HTTP POST |

## SDK Configuration

### OpenAI SDK (Python)
```python
from openai import OpenAI
client = OpenAI(api_key="sk-YOUR-KEY", base_url="https://api.lemondata.cc/v1")
```

### OpenAI SDK (JavaScript)
```javascript
import OpenAI from 'openai';
const client = new OpenAI({ apiKey: 'sk-YOUR-KEY', baseURL: 'https://api.lemondata.cc/v1' });
```

### Anthropic SDK (Python) — for Claude models
```python
from anthropic import Anthropic
client = Anthropic(api_key="sk-YOUR-KEY", base_url="https://api.lemondata.cc")  # No /v1
```

### Anthropic SDK (JavaScript) — for Claude models
```javascript
import Anthropic from '@anthropic-ai/sdk';
const client = new Anthropic({ apiKey: 'sk-YOUR-KEY', baseURL: 'https://api.lemondata.cc' });
```

### Google Gemini SDK (Python) — for Gemini models
```python
import google.generativeai as genai
genai.configure(api_key="sk-YOUR-KEY", transport="rest",
                client_options={"api_endpoint": "api.lemondata.cc"})
```

## Error Handling Best Practice

```python
from openai import OpenAI, APIError

client = OpenAI(api_key="sk-YOUR-KEY", base_url="https://api.lemondata.cc/v1")

try:
    response = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.choices[0].message.content)
except APIError as e:
    error = e.body.get("error", {}) if isinstance(e.body, dict) else {}

    if error.get("code") == "model_not_found":
        suggested = error.get("did_you_mean") or error.get("suggestions", [{}])[0].get("id")
        if suggested:
            response = client.chat.completions.create(
                model=suggested, messages=[{"role": "user", "content": "Hello!"}]
            )

    elif error.get("code") == "insufficient_balance":
        cheaper = error.get("suggestions", [{}])[0].get("id")
        if cheaper:
            response = client.chat.completions.create(
                model=cheaper, messages=[{"role": "user", "content": "Hello!"}]
            )

    elif error.get("retryable"):
        import time
        time.sleep(error.get("retry_after", 5))
        # Retry the same request
```

## Async Task Processing (Video/Music/3D)

```python
import time, requests

headers = {"Authorization": "Bearer sk-YOUR-KEY", "Content-Type": "application/json"}

# Submit
resp = requests.post("https://api.lemondata.cc/v1/video/generations",
    headers=headers, json={"model": "sora", "prompt": "A cat playing piano"})
task_id = resp.json()["id"]

# Poll
while True:
    status = requests.get(f"https://api.lemondata.cc/v1/video/generations/{task_id}",
        headers=headers).json()
    if status["status"] == "completed":
        print(f"URL: {status['video_url']}")
        break
    elif status["status"] == "failed":
        print(f"Error: {status['error']}")
        break
    time.sleep(5)
```

## Resources

- Website: https://lemondata.cc
- API Docs: https://docs.lemondata.cc
- llms.txt: https://lemondata.cc/llms.txt
- Models: https://lemondata.cc/en/models
- Dashboard: https://lemondata.cc/dashboard
