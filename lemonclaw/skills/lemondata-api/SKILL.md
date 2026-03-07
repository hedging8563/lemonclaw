---
name: lemondata-api
description: Call LemonData API for chat, images, video, music, 3D, TTS, STT, embeddings, and rerank. 300+ models, Agent-First error recovery. Use when user wants to generate content, query models, or interact with LemonData services.
metadata: { "lemonclaw": { "always": true, "requires": { "env": ["API_KEY"] } } }
triggers: 画图,生成图片,做视频,配音,音乐,3D,TTS,去背景,放大图片,embedding,嵌入,rerank,重排,转录,语音识别,STT,lemondata
---

# LemonData API

300+ AI models through a unified API. Agent-First design — errors tell you exactly how to self-correct.

## Authentication

**CRITICAL: You MUST use the `$API_KEY` environment variable. NEVER fabricate, guess, or hardcode an API key.**

```bash
# Correct:
curl -H "Authorization: Bearer $API_KEY" ...

# WRONG — never do this:
# curl -H "Authorization: Bearer sk-lemondata-..." ...
# curl -H "Authorization: Bearer $OPENAI_API_KEY" ...
# curl -H "Authorization: Bearer $LEMONDATA_API_KEY" ...
```

Base URL: `https://api.lemondata.cc`

## Agent-First Error Recovery

Do NOT search for docs before making an API call. Just try it. If it fails, the error response tells you what to do.

```
Workflow:
  1. Try the API call with your best guess
  2. If 400 model_not_found → read error.did_you_mean and error.suggestions → retry
  3. If 402 insufficient_balance → read error.balance_usd → switch to cheaper model
  4. If 429 rate_limit → read error.retry_after → wait and retry
  5. If 503 all_channels_failed → read error.alternatives → switch model or wait
  6. If 200 → check X-LemonData-Hint header for optimization tips
```

### Error Fields

Every error includes structured hints for self-correction:

| Field | Description |
|-------|-------------|
| `did_you_mean` | Closest matching model name |
| `suggestions` | Alternative models with pricing and tags |
| `alternatives` | Currently available models (on 503) |
| `hint` | Actionable guidance |
| `retryable` | Boolean — can retry succeed? |
| `retry_after` | Seconds to wait before retry |
| `balance_usd` | Current account balance (on 402) |
| `estimated_cost_usd` | Estimated request cost (on 402) |

## Endpoints

| Category | Method | Path |
|----------|--------|------|
| Chat (OpenAI) | POST | `/v1/chat/completions` |
| Chat (Anthropic) | POST | `/v1/messages` |
| Chat (Gemini) | POST | `/v1beta/models/{model}:generateContent` |
| Responses | POST | `/v1/responses` |
| Images | POST | `/v1/images/generations` |
| Image Edit | POST | `/v1/images/edits` |
| Video | POST | `/v1/videos/generations` |
| Video Status | GET | `/v1/videos/generations/{id}` |
| Music | POST | `/v1/music/generations` |
| Music Status | GET | `/v1/music/generations/{id}` |
| 3D | POST | `/v1/3d/generations` |
| 3D Status | GET | `/v1/3d/generations/{id}` |
| TTS | POST | `/v1/audio/speech` |
| STT | POST | `/v1/audio/transcriptions` |
| Embeddings | POST | `/v1/embeddings` |
| Rerank | POST | `/v1/rerank` |
| Models | GET | `/v1/models` |

## Model Discovery

```bash
# List all models
curl -s "https://api.lemondata.cc/v1/models" -H "Authorization: Bearer $API_KEY"

# Filter by category
curl -s "https://api.lemondata.cc/v1/models?category=image" -H "Authorization: Bearer $API_KEY"
# Categories: chat, image, video, audio, tts, stt, 3d, embedding, rerank

# Filter by tag
curl -s "https://api.lemondata.cc/v1/models?tag=coding" -H "Authorization: Bearer $API_KEY"
```

Or just guess the model name — if wrong, `error.did_you_mean` will correct you.

## Image Generation

`POST /v1/images/generations`

| Model | Best For | ~Cost |
|-------|----------|-------|
| `gpt-image-1` | General purpose, editing | $0.03 |
| `gemini-3-pro-image-preview` | High quality | $0.09 |
| `flux-pro` | Photorealistic | $0.04 |
| `mj-imagine` | Artistic, stylized | $0.07 |
| `ideogram-generate-v3` | Text in images | $0.01 |

```bash
curl -s https://api.lemondata.cc/v1/images/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-1","prompt":"A cat wearing sunglasses","n":1,"size":"1024x1024"}'
```

Response: `data[0].url` or `data[0].b64_json`.

### Image Tools

~$0.01/request. Send image via `image` (URL) or `image_base64` field.

| Model | Tool |
|-------|------|
| `image-background-remover` | Remove background |
| `image-upscaler` | Upscale image |
| `image-watermark-remover` | Remove watermark |

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

Returns `{"id":"task_xxx","status":"pending"}`. Poll:

```bash
curl -s "https://api.lemondata.cc/v1/videos/generations/task_xxx" \
  -H "Authorization: Bearer $API_KEY"
```

## Music Generation (Async)

`POST /v1/music/generations`

| Model | Use | ~Cost |
|-------|-----|-------|
| `suno-music` | Generate songs | $0.07 |
| `suno-lyrics` | Generate lyrics only | $0.01 |

Poll: `GET /v1/music/generations/{task_id}`.

## 3D Model Generation (Async)

`POST /v1/3d/generations` — Model: `tripo3d-v2.5` (~$0.14/request).

Poll: `GET /v1/3d/generations/{task_id}`.

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

## Speech-to-Text

`POST /v1/audio/transcriptions`

```bash
curl -s https://api.lemondata.cc/v1/audio/transcriptions \
  -H "Authorization: Bearer $API_KEY" \
  -F "model=whisper-1" \
  -F "file=@audio.mp3"
```

## Embeddings

`POST /v1/embeddings`

```bash
curl -s https://api.lemondata.cc/v1/embeddings \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"text-embedding-3-small","input":"Hello world"}'
```

## Rerank

`POST /v1/rerank`

```bash
curl -s https://api.lemondata.cc/v1/rerank \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"rerank-v3.5","query":"What is AI?","documents":["AI is...","The weather..."]}'
```

## Async Task Polling Pattern

Video, music, and 3D endpoints return a task ID. Use this pattern:

```bash
# 1. Submit task
RESPONSE=$(curl -s https://api.lemondata.cc/v1/videos/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sora-2","prompt":"..."}')
TASK_ID=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Poll every 10s until completed or failed
while true; do
  STATUS=$(curl -s "https://api.lemondata.cc/v1/videos/generations/$TASK_ID" \
    -H "Authorization: Bearer $API_KEY")
  STATE=$(echo $STATUS | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  if [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ]; then
    echo "$STATUS"
    break
  fi
  sleep 10
done
```

## Behavior

- "draw", "generate image", "画图", "生成图片" → Image Generation
- "make a video", "做视频", "生成视频" → Video Generation
- "music", "song", "音乐", "歌曲" → Music Generation
- "3D model", "3D 模型" → 3D Generation
- "read aloud", "TTS", "配音", "朗读" → Text-to-Speech
- "transcribe", "转录", "语音识别", "STT" → Speech-to-Text
- "embedding", "嵌入", "向量" → Embeddings
- "rerank", "重排" → Rerank
- "remove background", "upscale", "去背景", "放大" → Image Tools
- Inform users of approximate cost before generating
- For async tasks (video/music/3D), tell the user it may take 30s-5min, then poll every 10s
- After getting the result, send the media URL with a brief caption
- On error, read the structured error fields and self-correct — do NOT dump raw API responses to the user
