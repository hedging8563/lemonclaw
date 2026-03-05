"""Lightweight i18n for user-facing system messages.

Language is resolved from session metadata (``lang`` key).
Defaults to ``"en"`` when unset.  Only ``"zh"`` and ``"en"`` are supported.
"""

from __future__ import annotations

_MESSAGES: dict[str, dict[str, str]] = {
    "task_stopped": {
        "en": "⏹ Task stopped.",
        "zh": "⏹ 任务已停止。",
    },
    "llm_timeout": {
        "en": "LLM call timed out after {timeout}s. Please try again.",
        "zh": "LLM 调用超时（{timeout}s），请重试。",
    },
    "tool_repeated_fail": {
        "en": "Tool '{name}' failed repeatedly. Please try a different approach.",
        "zh": "工具 '{name}' 反复失败，请换个方式试试。",
    },
    "max_iterations": {
        "en": "Reached max tool call iterations ({n}). Try breaking the task into smaller steps.",
        "zh": "已达到最大工具调用次数（{n}），请尝试将任务拆分为更小的步骤。",
    },
    "no_response": {
        "en": "I've completed processing but have no response to give.",
        "zh": "处理完成，但没有需要回复的内容。",
    },
    "error": {
        "en": "Sorry, I encountered an error.",
        "zh": "抱歉，处理时出现了错误。",
    },
    "new_session": {
        "en": "New session started.",
        "zh": "已开始新会话。",
    },
    "memory_archival_failed": {
        "en": "Memory archival failed, session not cleared. Please try again.",
        "zh": "记忆归档失败，会话未清除，请重试。",
    },
    "help": {
        "en": (
            "🍋 LemonClaw commands:\n"
            "/new — Start a new conversation\n"
            "/stop — Stop the current task\n"
            "/model — List or switch models\n"
            "/usage — Show token usage\n"
            "/help — Show available commands"
        ),
        "zh": (
            "🍋 LemonClaw 命令：\n"
            "/new — 开始新会话\n"
            "/stop — 停止当前任务\n"
            "/model — 查看或切换模型\n"
            "/usage — 查看 Token 用量\n"
            "/help — 显示可用命令"
        ),
    },
    "no_model_match": {
        "en": "No model matching `{arg}`. Use `/model` to see available models.",
        "zh": "没有匹配 `{arg}` 的模型，使用 `/model` 查看可用模型。",
    },
    "model_switched": {
        "en": "Switched to **{label}** (`{id}`) — {desc}",
        "zh": "已切换到 **{label}** (`{id}`) — {desc}",
    },
    "stop_tasks": {
        "en": "⏹ Stopped {n} task(s).",
        "zh": "⏹ 已停止 {n} 个任务。",
    },
    "stop_none": {
        "en": "No active task to stop.",
        "zh": "没有正在运行的任务。",
    },
    "bg_task_done": {
        "en": "Background task completed.",
        "zh": "后台任务已完成。",
    },
    "empty_message": {
        "en": "Please enter a message.",
        "zh": "请输入消息内容。",
    },
    "unknown_command": {
        "en": "Unknown command `{cmd}`. Use `/help` to see available commands.",
        "zh": "未知命令 `{cmd}`，使用 `/help` 查看可用命令。",
    },
}


def t(key: str, lang: str = "en", **kwargs) -> str:
    """Get a translated message. Falls back to English if key/lang missing."""
    msgs = _MESSAGES.get(key, {})
    template = msgs.get(lang) or msgs.get("en", key)
    return template.format(**kwargs) if kwargs else template


def detect_lang(text: str) -> str:
    """Detect language from text. Returns 'zh' if >=30% CJK characters, else 'en'."""
    if not text:
        return "en"
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return "zh" if cjk / max(len(text.strip()), 1) >= 0.3 else "en"


def session_lang(session) -> str:
    """Extract language from a session object (metadata.lang), default 'en'."""
    if session and hasattr(session, "metadata"):
        return session.metadata.get("lang", "en")
    return "en"
