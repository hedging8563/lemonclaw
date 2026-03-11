# LemonClaw Skills

This directory contains LemonClaw's built-in skills.

Each skill lives in its own folder and must include a `SKILL.md` file with YAML frontmatter plus the markdown guidance loaded into agent context.

## Current Built-in Skills

| Skill | Purpose | Availability |
|-------|---------|--------------|
| `browser` | Browser automation for websites, forms, screenshots, and scraping | Requires `agent-browser` |
| `content-writer` | Long-form writing that avoids generic AI tone | Built in |
| `cron` | Scheduling reminders and recurring tasks | Built in |
| `docx` | Creating, editing, and reading Word documents | Built in |
| `frontend-design` | Building polished web pages and UI components | Built in |
| `github` | Working with GitHub through the `gh` CLI | Requires `gh` |
| `lemondata-api` | Calling LemonData chat, image, video, audio, and embedding APIs | Requires `API_KEY` |
| `mcp-builder` | Creating MCP servers in Python or TypeScript | Built in |
| `memory` | Two-layer memory workflow (`MEMORY.md` + `HISTORY.md`) | Always loaded |
| `pdf` | Reading, creating, editing, splitting, and extracting PDFs | Built in |
| `skill-creator` | Creating and packaging new skills with helper scripts | Built in |
| `skill-installer` | Installing, listing, and removing workspace skills | Built in |
| `summarize` | Summarizing URLs, files, podcasts, and YouTube links | Requires `summarize` |
| `tmux` | Driving interactive terminal sessions through tmux | Requires `tmux` |
| `weather` | Current weather and forecasts without an API key | Requires `curl` |
| `xlsx` | Reading and editing spreadsheets and tabular data | Built in |
| `yt-dlp` | Downloading videos and extracting audio from supported sites | Requires `yt-dlp` and `ffmpeg` |

## Notes

- Workspace skills in `~/.lemonclaw/workspace/skills/` override built-in skills with the same name.
- Skills with unmet `requires` metadata are filtered out from normal matching and marked unavailable in the WebUI.
- The skill catalog in this README is tested against the directory contents, so it should stay in sync with the source tree.
