---
name: lemondata-media
description: Generate images, videos, music, 3D models, and TTS via LemonData API. Use when user wants to create, generate, draw, or produce any media content.
metadata: { "lemonclaw": { "always": true, "requires": { "env": ["API_KEY"] } } }
---

# LemonData Media Generation

You have access to LemonData's multi-modal AI APIs. **Proactively offer** these capabilities when users mention anything related to images, videos, music, 3D, or audio.

## Authentication

All requests use: `Authorization: Bearer $API_KEY`

Base URL: `https://api.lemondata.cc/v1`

## Image Generation

`POST /v1/images/generations`

| Model | Best For | Cost |
|-------|----------|------|
| `gpt-image-1` | General purpose, editing | $0.028 |
| `gemini-3-pro-image-preview` | High quality, Google | $0.094 |
| `flux-pro` | Photorealistic | $0.037 |
| `mj-imagine` | Artistic, stylized | $0.07 |
| `ideogram-generate-v3` | Text in images, design | $0.014 |

```bash
curl -s https://api.lemondata.cc/v1/images/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-1","prompt":"A cat wearing sunglasses","n":1,"size":"1024x1024"}'
```

Response contains `data[0].url` (image URL) or `data[0].b64_json`.

## Video Generation (Async)

`POST /v1/videos/generations`

| Model | Best For | Cost |
|-------|----------|------|
| `veo3.1` | Highest quality | $0.28 |
| `sora-2` | OpenAI, balanced | $0.07 |
| `kling-v2.6-pro` | Motion control | $0.49 |
| `hailuo-2.3` | Budget friendly | $0.033 |

Submit:
```bash
curl -s https://api.lemondata.cc/v1/videos/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sora-2","prompt":"A golden retriever running on the beach"}'
```

Returns `{"id":"task_xxx","status":"pending"}`. Poll until complete (see Async Polling below).

## Music Generation (Async)

`POST /v1/music/generations`

| Model | Use | Cost |
|-------|-----|------|
| `suno-music` | Generate songs | $0.07 |
| `suno-lyrics` | Generate lyrics only | $0.014 |

```bash
curl -s https://api.lemondata.cc/v1/music/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"suno-music","prompt":"A relaxing lo-fi beat with piano"}'
```

## 3D Model Generation (Async)

`POST /v1/3d/generations`

Model: `tripo3d-v2.5` ($0.14/request). Accepts text prompt or image URL.

## Text-to-Speech

`POST /v1/audio/speech`

| Model | Quality | Cost |
|-------|---------|------|
| `tts-1-hd` | High definition | $21/M input |
| `gpt-4o-mini-tts` | Fast, affordable | $1.75/M input |

Voices: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`

```bash
curl -s https://api.lemondata.cc/v1/audio/speech \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1-hd","input":"Hello world","voice":"nova"}' \
  --output speech.mp3
```

## Image Tools

All tools cost $0.014/request. Send image via `image` (URL) or `image_base64` field.

| Endpoint | Tool |
|----------|------|
| `POST /v1/images/generations` with model `image-background-remover` | Remove background |
| `POST /v1/images/generations` with model `image-upscaler` | Upscale image |
| `POST /v1/images/generations` with model `image-watermark-remover` | Remove watermark |

## Async Task Polling

Video, music, and 3D tasks are async. After submitting, poll:

```bash
# Poll every 10s, max 60 attempts
curl -s "https://api.lemondata.cc/v1/{type}/generations/{task_id}" \
  -H "Authorization: Bearer $API_KEY"
```

Response: `{"status":"pending|processing|completed|failed", ...}`

When `status=completed`: video → `video_url`, music → `audio_url`, 3D → `model_url`.

## Discover More Models

```bash
curl -s https://api.lemondata.cc/v1/models \
  -H "Authorization: Bearer $API_KEY" | grep -i "keyword"
```

## Behavior Guidelines

- When users ask to "draw", "generate image", "make a picture" → use Image Generation
- When users ask to "make a video", "create animation" → use Video Generation
- When users ask for "music", "song", "beat" → use Music Generation
- When users ask for "3D model", "3D object" → use 3D Generation
- When users ask to "read aloud", "convert to speech", "TTS" → use Text-to-Speech
- When users share an image and ask to "remove background", "upscale", "remove watermark" → use Image Tools
- Always inform users of the approximate cost before generating
- For async tasks, inform users it may take 30s-5min and provide status updates

## Output Rules (CRITICAL)

- **NEVER** output your reasoning, planning, or thought process to the user
- **NEVER** say things like "Let me read the skill", "I'll use model X", "Let me generate..."
- **DO NOT** explain what you are about to do before doing it
- Execute the curl command IMMEDIATELY without preamble
- After getting the result, send ONLY the media (image/video/audio URL) with a brief friendly caption
- If an error occurs, report the error concisely without showing the raw API response
