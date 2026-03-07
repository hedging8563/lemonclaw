---
name: yt-dlp
description: "Download videos and extract audio from various platforms using yt-dlp. Use when user provides a video URL, asks to download a video, or when conversation contains video links from YouTube, Twitter/X, Vimeo, TikTok, Instagram, etc. Also triggers on 下载视频、下视频、下片、提取音频、视频下载、音频提取、下载YouTube、下载B站."
triggers: "youtube.com,youtu.be,bilibili.com,twitter.com,x.com,tiktok.com,instagram.com,vimeo.com,下载视频,下视频,下片,提取音频,视频下载,音频提取,下载youtube,下载b站,yt-dlp"
---

# yt-dlp Video Downloader Skill

Download videos and extract audio from various platforms using yt-dlp.

## Features

- Download videos from multiple platforms (YouTube, Twitter/X, Vimeo, TikTok, Instagram, Facebook, Bilibili, etc.)
- Extract audio from videos
- Auto-detect video URLs in conversations
- Support for different quality settings and formats

## Available Scripts

Scripts are located in the `scripts/` directory relative to this skill.

### download_video.py

Main video downloader with quality and format options.

```bash
# Download video
scripts/download_video.py <url> -o <output_dir>

# Download with specific quality
scripts/download_video.py <url> --quality 720p
scripts/download_video.py <url> --quality audio  # Audio only

# Custom format selector
scripts/download_video.py <url> --format "bestvideo[height<=1080]+bestaudio/best"

# Extract info only (no download)
scripts/download_video.py <url> --info-only
```

Quality options: `best`, `1080p`, `720p`, `480p`, `audio`

### extract_audio.py

Extract audio from videos in various formats.

```bash
# Extract as MP3 (default)
scripts/extract_audio.py <url> -o <output_dir>

# Extract as M4A
scripts/extract_audio.py <url> --format m4a

# Custom quality (kbps)
scripts/extract_audio.py <url> --quality 320
```

Formats: `mp3`, `m4a`, `opus`, `flac`, `wav`

### extract_urls.py

Extract video URLs from text or files.

```bash
# Extract from text
scripts/extract_urls.py "Check https://youtube.com/watch?v=..."

# Extract from file
scripts/extract_urls.py <file_path>

# Read from stdin
cat file.txt | scripts/extract_urls.py
```

## Supported Platforms

YouTube, Twitter/X, Vimeo, TikTok, Instagram, Facebook, Twitch, Dailymotion, Bilibili, Reddit, Streamable, NicoNico, and many more supported by yt-dlp.

## Workflow

1. Extract URL from user input using `extract_urls.py`
2. Confirm action: download video, extract audio, or show info
3. Execute appropriate script
4. Report success/failure and file location

## Defaults

- Video: best available quality
- Audio: MP3 at 192kbps

## Dependencies

- `yt-dlp`: Main downloader (`pip install yt-dlp` or `brew install yt-dlp`)
- `ffmpeg`: Required for format conversion (`brew install ffmpeg` or `apt install ffmpeg`)
- `python3` with standard library
