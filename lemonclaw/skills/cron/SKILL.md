---
name: cron
description: Schedule reminders and recurring tasks with the cron tool. Use when the user wants a reminder, repeated check, one-time schedule, or periodic automation.
metadata: {"lemonclaw":{"pattern":"generator"}}
triggers: "提醒我,定时,闹钟,每天,每周,每小时,日程,日历提醒,reminder,remind me,schedule,every day,every hour,crontab,定期,recurring task,calendar reminder"
---

# Cron

This skill is primarily a `generator`: convert the user's timing intent into the smallest correct `cron(...)` call.

## Entry Rule

Use this skill when the user wants:
- a one-time reminder
- a recurring reminder
- a periodic task LemonClaw should run later

If the user has not given enough timing information, gather the missing minimum before scheduling.

## Runtime Boundary

- Skill owns: parameter mapping and schedule shape.
- Runtime owns: persistence, delivery, retries, and actual execution.

## Choose The Simplest Mode

1. One-time reminder at a known moment → use `at`
2. Simple fixed interval → use `every_seconds`
3. Calendar-style recurring schedule → use `cron_expr`

Prefer the simplest representation that matches the user intent.

## Examples

Fixed reminder:
```text
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

One-time schedule:
```text
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware recurring schedule:
```text
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

List or remove:
```text
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Mapping Hints

| User says | Parameters |
|-----------|------------|
| every 20 minutes | `every_seconds=1200` |
| every hour | `every_seconds=3600` |
| every day at 8am | `cron_expr="0 8 * * *"` |
| weekdays at 5pm | `cron_expr="0 17 * * 1-5"` |
| 9am Vancouver time daily | `cron_expr="0 9 * * *", tz="America/Vancouver"` |
| at a specific time | `at="<ISO datetime>"` |

## Guardrails

- Do not invent a timezone when the user already implied local time.
- Use `tz` only when the user specifies a location/timezone or when server-local time would be ambiguous.
- If the user asks for a recurring task LemonClaw should execute, make the `message` self-sufficient so future runs know what to do.
