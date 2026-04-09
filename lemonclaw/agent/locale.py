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
    "tool_empty_args_write_file": {
        "en": "Tool 'write_file' was called without the required path/content. Please provide complete arguments, or use exec as a fallback to write the file.",
        "zh": "工具 'write_file' 调用时缺少必要的 path/content。请提供完整参数，或改用 exec 作为写文件兜底方案。",
    },
    "tool_empty_args_exec": {
        "en": "Tool 'exec' was called without the required command. Please provide a complete command before retrying.",
        "zh": "工具 'exec' 调用时缺少必要的 command。请补全命令后再重试。",
    },
    "tool_empty_args_coding": {
        "en": "Tool 'coding' was called without the required task. Please restate the concrete coding task before retrying, including the target files or desired outcome when possible. If the change is small, prefer direct tools such as exec/write_file instead.",
        "zh": "工具 'coding' 调用时缺少必要的 task。请先补全具体编码任务后再重试，最好带上目标文件或期望结果。如果只是小改动，优先直接使用 exec 或 write_file。",
    },
    "tool_empty_args_browser": {
        "en": "Tool 'browser' was called without the required command. Please provide a full browser command such as 'open https://example.com' or 'snapshot -i' before retrying.",
        "zh": "工具 'browser' 调用时缺少必要的 command。请先提供完整浏览器命令后再重试，例如 'open https://example.com' 或 'snapshot -i'。",
    },
    "tool_empty_args_required": {
        "en": "Tool '{name}' is missing required parameter(s): {fields}. Please provide complete parameters before retrying.",
        "zh": "工具 '{name}' 缺少必要参数：{fields}。请补全参数后再重试。",
    },
    "tool_empty_args_generic": {
        "en": "Tool '{name}' was called without the required arguments. Please provide complete parameters before retrying.",
        "zh": "工具 '{name}' 调用时缺少必要参数。请补全参数后再重试。",
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
            "/tasks [limit] — Show recent tasks and recovery hints\n"
            "/resume [task_id] — Run the safest available resume action\n"
            "/kb <query> — Search ingested knowledge\n"
            "/kb list — List knowledge documents\n"
            "/kb add <title> :: <content> — Add a manual knowledge note\n"
            "/model — List or switch models\n"
            "/git-auth — Manage saved Git push credentials\n"
            "/usage — Show token usage\n"
            "/help — Show available commands"
        ),
        "zh": (
            "🍋 LemonClaw 命令：\n"
            "/new — 开始新会话\n"
            "/stop — 停止当前任务\n"
            "/tasks [数量] — 查看最近任务与恢复建议\n"
            "/resume [task_id] — 执行当前最安全的恢复动作\n"
            "/kb <查询> — 搜索已入库知识\n"
            "/kb list — 列出知识文档\n"
            "/kb add <标题> :: <内容> — 新增手动知识\n"
            "/model — 查看或切换模型\n"
            "/git-auth — 管理 Git 远端推送凭证\n"
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
    "tasks_usage": {
        "en": "Use `/tasks` or `/tasks <limit>` to inspect recent tasks for this chat session.",
        "zh": "使用 `/tasks` 或 `/tasks <数量>` 查看当前聊天会话的最近任务。",
    },
    "tasks_empty": {
        "en": "No recent tasks were found for this chat session.",
        "zh": "当前聊天会话没有最近任务。",
    },
    "tasks_header": {
        "en": "Recent tasks for this chat session:",
        "zh": "当前聊天会话的最近任务：",
    },
    "tasks_item": {
        "en": "- {task_id}: status={status}, stage={stage}, next={action}, safe={safe}, reason={reason}",
        "zh": "- {task_id}：状态={status}，阶段={stage}，下一步={action}，可自动执行={safe}，原因={reason}",
    },
    "resume_usage": {
        "en": "Use `/resume` to resume the latest task, or `/resume <task_id>` to target a specific task from `/tasks`.",
        "zh": "使用 `/resume` 恢复最近任务，或使用 `/resume <task_id>` 恢复 `/tasks` 中的指定任务。",
    },
    "resume_not_found": {
        "en": "No resumable task matching `{task_id}` was found for this chat session.",
        "zh": "当前聊天会话没有找到匹配 `{task_id}` 的可恢复任务。",
    },
    "resume_unsafe": {
        "en": "Task `{task_id}` is not safe to resume automatically. Recommended action: {action}. Reason: {reason}",
        "zh": "任务 `{task_id}` 当前不适合自动恢复。建议动作：{action}。原因：{reason}",
    },
    "resume_executed": {
        "en": "Executed safe resume for `{task_id}`. Action: {action}. Reason: {reason}",
        "zh": "已对 `{task_id}` 执行安全恢复。动作：{action}。原因：{reason}",
    },
    "resume_scheduled": {
        "en": "Scheduled safe resume for `{task_id}` in the background. Action: {action}. Reason: {reason}",
        "zh": "已在后台为 `{task_id}` 安排安全恢复。动作：{action}。原因：{reason}",
    },
    "resume_failed": {
        "en": "Failed to resume `{task_id}`: {error}",
        "zh": "恢复 `{task_id}` 失败：{error}",
    },
    "git_auth_usage": {
        "en": (
            "Git auth commands:\n"
            "/git-auth list — List saved Git credential profiles\n"
            "/git-auth show <name> — Show one profile (password stays masked)\n"
            "/git-auth set <name> :: <token> — Save a profile with username x-access-token\n"
            "/git-auth set <name> :: <username> :: <token> — Save a profile with a custom username\n"
            "/git-auth delete <name> — Remove one profile"
        ),
        "zh": (
            "Git 凭证命令：\n"
            "/git-auth list — 列出已保存的 Git 凭证配置\n"
            "/git-auth show <name> — 查看单个配置（密码保持脱敏）\n"
            "/git-auth set <name> :: <token> — 保存一个默认用户名为 x-access-token 的配置\n"
            "/git-auth set <name> :: <username> :: <token> — 保存一个自定义用户名的配置\n"
            "/git-auth delete <name> — 删除一个配置"
        ),
    },
    "git_auth_list_empty": {
        "en": "No saved Git auth profiles yet.",
        "zh": "当前还没有已保存的 Git 凭证配置。",
    },
    "git_auth_list_header": {
        "en": "Saved Git auth profiles:",
        "zh": "已保存的 Git 凭证配置：",
    },
    "git_auth_list_item": {
        "en": "- {name} (username={username}, status={status})",
        "zh": "- {name}（username={username}，状态={status}）",
    },
    "git_auth_status_ready": {
        "en": "ready",
        "zh": "已就绪",
    },
    "git_auth_status_missing": {
        "en": "missing password",
        "zh": "缺少密码",
    },
    "git_auth_not_found": {
        "en": "Git auth profile `{name}` was not found.",
        "zh": "没有找到 Git 凭证配置 `{name}`。",
    },
    "git_auth_saved": {
        "en": "Saved Git auth profile `{name}` for username `{username}`. Future remote pushes can use auth_profile=`{name}`.",
        "zh": "已保存 Git 凭证配置 `{name}`，用户名为 `{username}`。之后远端 push 可以使用 auth_profile=`{name}`。",
    },
    "git_auth_deleted": {
        "en": "Deleted Git auth profile `{name}`.",
        "zh": "已删除 Git 凭证配置 `{name}`。",
    },
    "git_auth_show": {
        "en": "Git auth profile `{name}`\nusername: {username}\npassword: {password}",
        "zh": "Git 凭证配置 `{name}`\nusername: {username}\npassword: {password}",
    },
    "git_auth_invalid_name": {
        "en": "Invalid Git auth profile name `{name}`. Use letters, numbers, dots, underscores, or dashes.",
        "zh": "Git 凭证配置名称 `{name}` 无效。请只使用字母、数字、点、下划线或连字符。",
    },
    "git_auth_save_failed": {
        "en": "Failed to update Git auth profile: {error}",
        "zh": "更新 Git 凭证配置失败：{error}",
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
