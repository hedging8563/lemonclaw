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
            "/kb <query> — Search ingested knowledge\n"
            "/kb list — List knowledge documents\n"
            "/kb add <title> :: <content> — Add a manual knowledge note\n"
            "/model — List or switch models\n"
            "/usage — Show token usage\n"
            "/help — Show available commands"
        ),
        "zh": (
            "🍋 LemonClaw 命令：\n"
            "/new — 开始新会话\n"
            "/stop — 停止当前任务\n"
            "/kb <查询> — 搜索已入库知识\n"
            "/kb list — 列出知识文档\n"
            "/kb add <标题> :: <内容> — 新增手动知识\n"
            "/model — 查看或切换模型\n"
            "/usage — 查看 Token 用量\n"
            "/help — 显示可用命令"
        ),
    },
    "no_model_match": {
        "en": "No model matching `{arg}`. Use `/model` to see available models.",
        "zh": "没有匹配 `{arg}` 的模型，使用 `/model` 查看可用模型。",
    },
    "model_switched_new_context": {
        "en": "Switched to **{label}** (`{id}`) — {desc}\nDetected a provider change, so a fresh session context has been started automatically.",
        "zh": "已切换到 **{label}** (`{id}`) — {desc}\n检测到供应商变更，系统已自动开启新的会话上下文。",
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
    "kb_usage": {
        "en": (
            "Knowledge commands:\n"
            "/kb <query> — Search ingested knowledge\n"
            "/kb list [limit] — List knowledge documents\n"
            "/kb add <title> :: <content> — Add a manual knowledge note\n"
            "/kb show <doc_id> — Show one knowledge document\n"
            "/kb pin <doc_id> — Pin a knowledge document\n"
            "/kb unpin <doc_id> — Unpin a knowledge document"
        ),
        "zh": (
            "知识命令：\n"
            "/kb <查询> — 搜索已入库知识\n"
            "/kb list [数量] — 列出知识文档\n"
            "/kb add <标题> :: <内容> — 新增手动知识\n"
            "/kb show <doc_id> — 查看知识文档\n"
            "/kb pin <doc_id> — 置顶知识文档\n"
            "/kb unpin <doc_id> — 取消置顶知识文档"
        ),
    },
    "kb_empty": {
        "en": "No knowledge hits for `{query}`.",
        "zh": "没有命中 `{query}` 的知识结果。",
    },
    "kb_add_usage": {
        "en": "Use `/kb add <title> :: <content>` to add a manual knowledge note.",
        "zh": "使用 `/kb add <标题> :: <内容>` 来新增手动知识。",
    },
    "kb_added": {
        "en": "Added knowledge note **{title}** (`{doc_id}`) and ingested it.",
        "zh": "已新增知识 **{title}** (`{doc_id}`) 并完成入库。",
    },
    "kb_add_failed": {
        "en": "Failed to add knowledge note: {error}",
        "zh": "新增知识失败：{error}",
    },
    "kb_list_empty": {
        "en": "No knowledge documents yet. Use `/kb add <title> :: <content>` to create one.",
        "zh": "还没有知识文档。可使用 `/kb add <标题> :: <内容>` 新建。",
    },
    "kb_pin_usage": {
        "en": "Use `/kb pin <doc_id>` or `/kb unpin <doc_id>`.",
        "zh": "使用 `/kb pin <doc_id>` 或 `/kb unpin <doc_id>`。",
    },
    "kb_show_usage": {
        "en": "Use `/kb show <doc_id>` to inspect one knowledge document.",
        "zh": "使用 `/kb show <doc_id>` 查看单个知识文档。",
    },
    "kb_pin_not_found": {
        "en": "Knowledge document `{doc_id}` was not found.",
        "zh": "没有找到知识文档 `{doc_id}`。",
    },
    "kb_pinned": {
        "en": "Pinned knowledge document **{title}** (`{doc_id}`).",
        "zh": "已置顶知识文档 **{title}** (`{doc_id}`)。",
    },
    "kb_unpinned": {
        "en": "Unpinned knowledge document **{title}** (`{doc_id}`).",
        "zh": "已取消置顶知识文档 **{title}** (`{doc_id}`)。",
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
