---
name: lemondata-api
description: Call LemonData APIs for chat, images, video, music, 3D, TTS, STT, embeddings, and rerank. Use when the user wants LemonData generation or model discovery, especially for non-chat workflows that require live model truth.
metadata: {"lemonclaw":{"always":true,"pattern":"tool-wrapper","requires":{"env":["API_KEY"]}}}
triggers: "lemondata,画图,生成图片,做视频,生成视频,音乐,歌曲,3D,TTS,STT,embedding,嵌入,rerank,重排,转录,语音识别,remove background,upscale"
---

# LemonData API

This is a `tool-wrapper` skill. Keep it lean and rely on live API truth.

Load these references only when needed:
- [references/nonchat-truth.md](references/nonchat-truth.md) for non-chat discovery and recovery rules
- [references/endpoint-recipes.md](references/endpoint-recipes.md) for concrete request examples

## Entry Rule

Use this skill when the user explicitly wants LemonData APIs, model discovery, or non-chat generation through LemonData.

Do not use this skill for generic public-web research or for provider-specific SDK questions that are not about LemonData.

## Runtime Boundary

- Skill owns: model-selection rules, API conventions, request recipes, error interpretation.
- Runtime owns: durable task polling, retries with side effects, delivery, billing visibility, and fail-closed gating.

## Authentication

Always use `Authorization: Bearer $API_KEY`.

Never invent or hardcode a key. Never substitute another provider key.

Base URL: `https://api.lemondata.cc`

## Core Rule: Chat And Non-Chat Are Different

### Chat / Responses

For chat-style requests:
- you may try a reasonable model first
- if the API returns a structured correction hint, use it

### Non-chat

For image, video, music, 3D, TTS, STT, embeddings, and rerank:
- do not trust memory
- do not recommend models from stale examples
- read live model truth first

Preferred path inside LemonClaw:
- use `lemondata_nonchat(action="discover", category="...")`
- then use `lemondata_nonchat(action="request", ...)`

If the helper is unavailable, read `/v1/models?category=<category>` before suggesting or calling a model.

## Non-Chat Recovery

If a non-chat request returns:
- `model_disabled`
- `model_not_found`
- `model_unavailable`
- `all_channels_failed`

then:
1. re-read the live category list
2. re-pick only from the fresh result
3. explain the switch using the live result

## Error Handling

Read structured error fields before deciding the next action:
- `did_you_mean`
- `suggestions`
- `alternatives`
- `hint`
- `retryable`
- `retry_after`
- `balance_usd`
- `estimated_cost_usd`

Do not dump raw API payloads to the user when a brief explanation is enough.

## Async Jobs

Video, music, and 3D are async.

Tell the user the task may take time, then poll status until the job reaches a terminal state. Let runtime/task orchestration own long-lived polling when available; do not emulate a durable workflow inside the skill alone.

## Quick Routing

- image generation or edit → non-chat discovery, then image endpoint
- video generation → non-chat discovery, then async video endpoint
- music generation → non-chat discovery, then async music endpoint
- 3D generation → non-chat discovery, then async 3D endpoint
- TTS / STT / embeddings / rerank → non-chat discovery, then the matching endpoint

If you need concrete request bodies, load [references/endpoint-recipes.md](references/endpoint-recipes.md).
