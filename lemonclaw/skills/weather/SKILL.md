---
name: weather
description: Get current weather and forecasts without an API key.
homepage: https://wttr.in/:help
metadata: {"lemonclaw":{"emoji":"🌤️","pattern":"tool-wrapper","requires":{"bins":["curl"]}}}
triggers: "天气,气温,下雨,天气预报,今日天气,明天天气,weather,forecast,温度,几度,穿什么,what's the weather,today's weather"
---

# Weather

This is a `tool-wrapper` skill.

## Entry Rule

Use this skill for simple weather and forecast questions.

## Primary Source

Use `wttr.in` first:

```bash
curl -s "wttr.in/London?format=3"
curl -s "wttr.in/New+York?format=%l:+%c+%t+%h+%w"
curl -s "wttr.in/London?T"
```

## Fallback

Use Open-Meteo when JSON output or explicit coordinates are needed:

```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

## Guardrails

- URL-encode spaces in location names.
- Clarify location if the user’s place is ambiguous.
- Keep the answer brief unless the user asks for a detailed forecast.
