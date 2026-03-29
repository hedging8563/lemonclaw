---
name: yt-dlp
description: Download videos or extract audio with yt-dlp. Use when the user provides a supported video URL or explicitly asks to download media or extract audio.
metadata: {"lemonclaw":{"emoji":"🎬","pattern":"tool-wrapper","requires":{"bins":["yt-dlp","ffmpeg"]}}}
triggers: "youtube.com,youtu.be,bilibili.com,twitter.com,x.com,tiktok.com,instagram.com,vimeo.com,download video,extract audio,video url,video link,youtube video,下载视频,下视频,下片,提取音频,视频下载,音频提取,下载youtube,下载b站,yt-dlp"
---

# yt-dlp

This is a `tool-wrapper` skill. Prefer the bundled scripts over ad-hoc shell assembly.

## Entry Rule

Use this skill when the user wants to:
- download a video
- extract audio from a video
- inspect a supported media URL

## Runtime Boundary

- Skill owns: tool choice, quality selection, and verification.
- Runtime owns: larger download pipelines and follow-up delivery.

## Workflow

1. Extract or confirm the URL.
2. Choose the action: info, video download, or audio extraction.
3. Run the matching script.
4. Verify the output path and report it clearly.

## Scripts

Download video:
```bash
scripts/download_video.py <url> -o <output_dir>
scripts/download_video.py <url> --quality 720p
scripts/download_video.py <url> --info-only
```

Extract audio:
```bash
scripts/extract_audio.py <url> -o <output_dir>
scripts/extract_audio.py <url> --format m4a
```

Extract URLs from text:
```bash
scripts/extract_urls.py "Check https://youtube.com/watch?v=..."
```

## Defaults

- Video: best available quality
- Audio: MP3 at 192kbps

## Guardrails

- Do not claim a download succeeded until you verify the output file.
- Prefer `--info-only` when the user asked to inspect before downloading.
- If conversion is needed, remember `ffmpeg` is part of the required runtime.
