---
name: lemondata-media
description: Generate images, videos, music, 3D models, and TTS via LemonData API. Use when user wants to create, generate, draw, or produce any media content. Triggers on 画图、生成图片、做视频、配音、音乐、3D、TTS、去背景、放大图片.
metadata: { "lemonclaw": { "always": true, "requires": { "env": ["API_KEY"] } } }
---

# LemonData Media Generation

Proactively offer these capabilities when users mention images, videos, music, 3D, or audio.

## Authentication

**CRITICAL: You MUST use the `$API_KEY` environment variable. NEVER fabricate, guess, or hardcode an API key.**

```bash
# Correct — always use the environment variable:
curl -H "Authorization: Bearer $API_KEY" ...

# WRONG — never do this:
# curl -H "Authorization: Bearer sk-lemondata-..." ...
```

Base URL: `https://api.lemondata.cc/v1`

## Image Generation

`POST /v1/images/generations`

| Model | Best For | ~Cost |
|-------|----------|-------|
| `gpt-image-1` | General purpose, editing | $0.03 |
| `gemini-3-pro-image-preview` | High quality, Google | $0.09 |
| `flux-pro` | Photorealistic | $0.04 |
| `mj-imagine` | Artistic, stylized | $0.07 |
| `ideogram-generate-v3` | Text in images, design | $0.01 |

Costs are approximate. Check `/v1/models` for current pricing.

```bash
curl -s https://api.lemondata.cc/v1/images/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-1","prompt":"A cat wearing sunglasses","n":1,"size":"1024x1024"}'
```

Response: `data[0].url` (image URL) or `data[0].b64_json`.

## Video Generation (Async)

`POST /v1/videos/generations`

| Model | Best For | ~Cost |
|-------|----------|-------|
| `veo3.1` | Highest quality | $0.28 |
| `sora-2` | OpenAI, balanced | $0.07 |
| `kling-v2.6-pro` | Motion control | $0.49 |
| `hailuo-2.3` | Budget friendly | $0.03 |

```bash
curl -s https://api.lemondata.cc/v1/videos/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sora-2","prompt":"A golden retriever running on the beach"}'
```

Returns `{"id":"task_xxx","status":"pending"}`. Poll with:

```bash
curl -s "https://api.lemondata.cc/v1/videos/generations/task_xxx" \
  -H "Authorization: Bearer $API_KEY"
```

When `status=completed`, response contains `video_url`.

## Music Generation (Async)

`POST /v1/music/generations`

| Model | Use | ~Cost |
|-------|-----|-------|
| `suno-music` | Generate songs | $0.07 |
| `suno-lyrics` | Generate lyrics only | $0.01 |

```bash
curl -s https://api.lemondata.cc/v1/music/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"suno-music","prompt":"A relaxing lo-fi beat with piano"}'
```

Poll: `GET /v1/music/generations/{task_id}`. When `status=completed`, response contains `audio_url`.

## 3D Model Generation (Async)

`POST /v1/3d/generations`

Model: `tripo3d-v2.5` (~$0.14/request). Accepts text prompt or image URL.

Poll: `GET /v1/3d/generations/{task_id}`. When `status=completed`, response contains `model_url`.

## Text-to-Speech

`POST /v1/audio/speech`

| Model | Quality | ~Cost |
|-------|---------|-------|
| `tts-1-hd` | High definition | $21/M chars |
| `gpt-4o-mini-tts` | Fast, affordable | $1.75/M chars |

Voices: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`

```bash
curl -s https://api.lemondata.cc/v1/audio/speech \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1-hd","input":"Hello world","voice":"nova"}' \
  --output speech.mp3
```

## Image Tools

~$0.01/request. Send image via `image` (URL) or `image_base64` field.

| Model | Tool |
|-------|------|
| `image-background-remover` | Remove background |
| `image-upscaler` | Upscale image |
| `image-watermark-remover` | Remove watermark |

All use `POST /v1/images/generations` with the model name above.

## Behavior

- "draw", "generate image", "画图", "生成图片" → Image Generation
- "make a video", "做视频", "生成视频" → Video Generation
- "music", "song", "音乐", "歌曲" → Music Generation
- "3D model", "3D 模型" → 3D Generation
- "read aloud", "TTS", "配音", "朗读" → Text-to-Speech
- "remove background", "upscale", "去背景", "放大" → Image Tools
- Inform users of approximate cost before generating
- For async tasks (video/music/3D), tell the user it may take 30s–5min, then poll every 10s
- After getting the result, send the media URL with a brief caption
- On error, report concisely without dumping raw API response
