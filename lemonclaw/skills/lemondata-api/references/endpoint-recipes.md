# LemonData Endpoint Recipes

Use these recipes only after the model has been validated against live discovery when the task is non-chat.

## Chat / Responses

```bash
curl -s https://api.lemondata.cc/v1/responses \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.2","input":"Hello"}'
```

## Image Generation

```bash
curl -s https://api.lemondata.cc/v1/images/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-1","prompt":"A cat wearing sunglasses","n":1,"size":"1024x1024"}'
```

Tool form:

```text
lemondata_nonchat(
  action="request",
  category="image",
  model="gpt-image-1",
  payload={
    "prompt":"A cat wearing sunglasses",
    "n":1,
    "size":"1024x1024"
  }
)
```

## Image Edit

Local file upload:

```text
lemondata_nonchat(
  action="request",
  category="image",
  endpoint="/v1/images/edits",
  model="flux-kontext-pro",
  payload={
    "prompt":"Keep the composition, replace the background with a rainy neon alley"
  },
  files={
    "image_path":"attachments/source.png",
    "mask_path":"attachments/mask.png"
  }
)
```

JSON / remote URL form:

```text
lemondata_nonchat(
  action="request",
  category="image",
  endpoint="/v1/images/edits",
  model="gpt-image-1",
  payload={
    "prompt":"Add a red umbrella",
    "image_url":"https://example.com/source.png"
  }
)
```

## Image Variation

```text
lemondata_nonchat(
  action="request",
  category="image",
  endpoint="/v1/images/variations",
  model="dall-e-2",
  payload={
    "n":1,
    "size":"1024x1024"
  },
  files={
    "image_path":"attachments/source.png"
  }
)
```

## Video Generation

```bash
curl -s https://api.lemondata.cc/v1/videos/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-video-model>","prompt":"A calm aerial shot of a rainy city at night"}'
```

Poll:

```bash
curl -s "https://api.lemondata.cc/v1/videos/generations/<task_id>" \
  -H "Authorization: Bearer $API_KEY"
```

## Music Generation

```bash
curl -s https://api.lemondata.cc/v1/music/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-music-model>","prompt":"Ambient piano with soft rain"}'
```

## 3D Generation

```bash
curl -s https://api.lemondata.cc/v1/3d/generations \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-3d-model>","prompt":"A stylized ceramic teapot"}'
```

## TTS

```bash
curl -s https://api.lemondata.cc/v1/audio/speech \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-tts-model>","input":"Hello world","voice":"nova"}' \
  --output speech.mp3
```

Tool form:

```text
lemondata_nonchat(
  action="request",
  category="tts",
  model="<live-tts-model>",
  payload={
    "input":"Hello world",
    "voice":"nova"
  },
  save_to="outputs/speech.mp3"
)
```

## STT

```bash
curl -s https://api.lemondata.cc/v1/audio/transcriptions \
  -H "Authorization: Bearer $API_KEY" \
  -F "model=<live-stt-model>" \
  -F "file=@audio.mp3"
```

Tool form:

```text
lemondata_nonchat(
  action="request",
  category="stt",
  model="<live-stt-model>",
  files={
    "audio_path":"attachments/audio.mp3"
  },
  payload={
    "language":"en"
  }
)
```

## Embeddings

```bash
curl -s https://api.lemondata.cc/v1/embeddings \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-embedding-model>","input":"Hello world"}'
```

## Rerank

```bash
curl -s https://api.lemondata.cc/v1/rerank \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"<live-rerank-model>","query":"What is AI?","documents":["AI is...","The weather..."]}'
```
