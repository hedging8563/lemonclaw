# LemonData Non-Chat Truth Rules

Use this reference when the task involves image, video, music, 3D, TTS, STT, embeddings, or rerank.

## Discovery First

Preferred inside LemonClaw runtime:

```text
lemondata_nonchat(action="discover", category="<category>")
```

Fallback:

```bash
curl -s "https://api.lemondata.cc/v1/models?category=<category>" \
  -H "Authorization: Bearer $API_KEY"
```

## Categories

- `image`
- `video`
- `audio`
- `tts`
- `stt`
- `3d`
- `embedding`
- `rerank`

## Failures That Require Fresh Discovery

Re-read the live category list after:

- `model_disabled`
- `model_not_found`
- `model_unavailable`
- `all_channels_failed`

## Recommendation Rule

Only recommend or call a non-chat model that appears in the fresh discovery result.

Do not:
- guess from memory
- rely on older session state
- free-associate a “similar” model

## When To Escalate

Stop and explain the blocker instead of looping when:
- no valid alternative exists in the fresh category list
- the error is not marked retryable
- balance is insufficient and the user has not asked to switch cost tiers
