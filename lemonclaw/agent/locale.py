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
            "/retry-outbox [task_id] — Retry failed outbox delivery when safe\n"
            "/recheck [task_id] — Re-run completion/recovery checks when safe\n"
            "/abandon [task_id] — Abandon the latest active outbox event for a task\n"
            "/export [task_id] [md|json] — Render the full task export artifact in chat\n"
            "/bundle [task_id] [md|json] — Show a compact summary or the full task bundle artifact\n"
            "/postmortem [task_id] [md|json] — Show a concise summary or the full postmortem artifact\n"
            "/runtime [inventory|mcp|health|recovery] — Show runtime, MCP, health, and recovery status\n"
            "/recovery [limit] [manual] — Show current-session recovery queue summary\n"
            "/channel status [name] — Show channel status in chat\n"
            "/channel restart <name> — Restart a channel from chat\n"
            "/channel repair <name> — Run channel repair from chat (currently includes WhatsApp)\n"
            "/kb <query> — Search ingested knowledge\n"
            "/kb list — List knowledge documents\n"
            "/kb add <title> :: <content> — Add a manual knowledge note\n"
            "/kb retry-failed [limit] — Retry failed knowledge ingests\n"
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
            "/retry-outbox [task_id] — 在安全前提下重试失败的 outbox 投递\n"
            "/recheck [task_id] — 在安全前提下重新执行完成/恢复检查\n"
            "/abandon [task_id] — 放弃任务最近的活跃 outbox 事件\n"
            "/export [task_id] [md|json] — 在聊天中渲染完整任务导出产物\n"
            "/bundle [task_id] [md|json] — 查看紧凑摘要或完整 task bundle 产物\n"
            "/postmortem [task_id] [md|json] — 查看简要摘要或完整 postmortem 产物\n"
            "/runtime [inventory|mcp|health|recovery] — 查看运行时、MCP、健康与恢复状态\n"
            "/recovery [数量] [manual] — 查看当前会话的恢复队列摘要\n"
            "/channel status [name] — 查看渠道状态\n"
            "/channel restart <name> — 在聊天中重启渠道\n"
            "/channel repair <name> — 在聊天中执行渠道修复（当前包含 WhatsApp）\n"
            "/kb <查询> — 搜索已入库知识\n"
            "/kb list — 列出知识文档\n"
            "/kb add <标题> :: <内容> — 新增手动知识\n"
            "/kb retry-failed [数量] — 重试失败的知识入库\n"
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
    "recovery_usage": {
        "en": "Use `/recovery`, `/recovery <limit>`, or append `manual` to only show tasks that still require manual review in this chat session.",
        "zh": "使用 `/recovery`、`/recovery <数量>`，或追加 `manual` 只查看当前聊天会话中仍需人工处理的任务。",
    },
    "recovery_empty": {
        "en": "No recovery tasks need attention for this chat session.",
        "zh": "当前聊天会话没有需要关注的恢复任务。",
    },
    "recovery_header": {
        "en": "Recovery queue for this chat session:",
        "zh": "当前聊天会话的恢复队列：",
    },
    "recovery_summary": {
        "en": "- Summary: tasks={tasks}, manual_review={manual_review}, stale_failed={stale_failed}, waiting_manual={waiting_manual}",
        "zh": "- 摘要：任务={tasks}，人工处理={manual_review}，陈旧恢复失败={stale_failed}，等待人工={waiting_manual}",
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
    "retry_outbox_usage": {
        "en": "Use `/retry-outbox` to target the latest task, or `/retry-outbox <task_id>` for a specific task from `/tasks`.",
        "zh": "使用 `/retry-outbox` 重试最近任务，或 `/retry-outbox <task_id>` 重试 `/tasks` 中的指定任务。",
    },
    "retry_outbox_unsafe": {
        "en": "Task `{task_id}` is not currently in a safe retry-outbox state. Recommended action: {action}. Reason: {reason}",
        "zh": "任务 `{task_id}` 当前不适合执行 retry-outbox。建议动作：{action}。原因：{reason}",
    },
    "retry_outbox_done": {
        "en": "Retried outbox delivery for `{task_id}`. Reason: {reason}",
        "zh": "已为 `{task_id}` 重试 outbox 投递。原因：{reason}",
    },
    "recheck_usage": {
        "en": "Use `/recheck` to target the latest task, or `/recheck <task_id>` for a specific task from `/tasks`.",
        "zh": "使用 `/recheck` 检查最近任务，或 `/recheck <task_id>` 检查 `/tasks` 中的指定任务。",
    },
    "recheck_unsafe": {
        "en": "Task `{task_id}` is not currently in a safe recheck state. Recommended action: {action}. Reason: {reason}",
        "zh": "任务 `{task_id}` 当前不适合执行 recheck。建议动作：{action}。原因：{reason}",
    },
    "recheck_done": {
        "en": "Rechecked `{task_id}`. Reason: {reason}",
        "zh": "已为 `{task_id}` 执行 recheck。原因：{reason}",
    },
    "abandon_usage": {
        "en": "Use `/abandon` to target the latest task, or `/abandon <task_id>` for a specific task from `/tasks`.",
        "zh": "使用 `/abandon` 放弃最近任务，或 `/abandon <task_id>` 放弃 `/tasks` 中的指定任务。",
    },
    "abandon_not_found": {
        "en": "No active outbox event is available to abandon for `{task_id}` in this chat session.",
        "zh": "当前聊天会话中没有可为 `{task_id}` 放弃的活跃 outbox 事件。",
    },
    "abandon_done": {
        "en": "Abandoned outbox event `{event_id}` for `{task_id}`. Reason: {reason}",
        "zh": "已为 `{task_id}` 放弃 outbox 事件 `{event_id}`。原因：{reason}",
    },
    "export_usage": {
        "en": "Use `/export` to render the latest task export in chat, `/export <task_id>` for a specific task, or append `md` / `json` to choose the output format.",
        "zh": "使用 `/export` 在聊天中渲染最近任务的 export，使用 `/export <task_id>` 指定任务，并可追加 `md` / `json` 选择输出格式。",
    },
    "export_not_found": {
        "en": "No export artifact is available for `{task_id}` in this chat session.",
        "zh": "当前聊天会话中没有 `{task_id}` 的 export 产物。",
    },
    "artifact_exported": {
        "en": "Rendered `{artifact}` for `{task_id}` as `{format}`.",
        "zh": "已将 `{task_id}` 的 `{artifact}` 以 `{format}` 形式渲染出来。",
    },
    "bundle_usage": {
        "en": "Use `/bundle` to inspect the latest task, `/bundle <task_id>` for a specific task, or append `md` / `json` to render the full bundle artifact in chat.",
        "zh": "使用 `/bundle` 查看最近任务，使用 `/bundle <task_id>` 指定任务，并可追加 `md` / `json` 在聊天中渲染完整 bundle 产物。",
    },
    "bundle_not_found": {
        "en": "No bundle is available for `{task_id}` in this chat session.",
        "zh": "当前聊天会话中没有 `{task_id}` 的 bundle。",
    },
    "bundle_header": {
        "en": "Bundle for `{task_id}`:",
        "zh": "`{task_id}` 的 bundle：",
    },
    "bundle_state": {
        "en": "- status={status}, stage={stage}, display={display}, next={action}, safe={safe}",
        "zh": "- 状态={status}，阶段={stage}，展示={display}，下一步={action}，可自动执行={safe}",
    },
    "bundle_verification": {
        "en": "- verification={verification_status}, evidence={evidence_count}",
        "zh": "- verification={verification_status}，证据数={evidence_count}",
    },
    "bundle_retrieval": {
        "en": "- retrieval strategy={strategy}, cards={cards}, rules={rules}, knowledge={knowledge}",
        "zh": "- retrieval strategy={strategy}，cards={cards}，rules={rules}，knowledge={knowledge}",
    },
    "bundle_outbox": {
        "en": "- outbox total={total}, active={active}, terminal={terminal}, failed={failed}",
        "zh": "- outbox total={total}，active={active}，terminal={terminal}，failed={failed}",
    },
    "bundle_conductor": {
        "en": "- conductor template={template}, subtasks={subtasks}, accepted={accepted}, failed={failed}",
        "zh": "- conductor template={template}，subtasks={subtasks}，accepted={accepted}，failed={failed}",
    },
    "postmortem_usage": {
        "en": "Use `/postmortem` to inspect the latest task, `/postmortem <task_id>` for a specific task, or append `md` / `json` to render the full postmortem artifact in chat.",
        "zh": "使用 `/postmortem` 查看最近任务，使用 `/postmortem <task_id>` 指定任务，并可追加 `md` / `json` 在聊天中渲染完整 postmortem 产物。",
    },
    "postmortem_not_found": {
        "en": "No postmortem is available for `{task_id}` in this chat session.",
        "zh": "当前聊天会话中没有 `{task_id}` 的 postmortem。",
    },
    "postmortem_header": {
        "en": "Postmortem for `{task_id}`:",
        "zh": "`{task_id}` 的 postmortem：",
    },
    "postmortem_state": {
        "en": "- status={status}, stage={stage}, display={display}, next={action}, safe={safe}",
        "zh": "- 状态={status}，阶段={stage}，展示={display}，下一步={action}，可自动执行={safe}",
    },
    "postmortem_recovery": {
        "en": "- recovery source={source}, action={recovery_action}, reason={reason}",
        "zh": "- 恢复 source={source}，action={recovery_action}，reason={reason}",
    },
    "postmortem_outbox": {
        "en": "- outbox failed={failed}, active={active}, terminal={terminal}",
        "zh": "- outbox failed={failed}，active={active}，terminal={terminal}",
    },
    "postmortem_steps": {
        "en": "- steps={steps}, last_successful_step={last_successful_step}",
        "zh": "- steps={steps}，last_successful_step={last_successful_step}",
    },
    "runtime_usage": {
        "en": "Use `/runtime`, `/runtime inventory`, `/runtime mcp`, `/runtime health`, or `/runtime recovery`.",
        "zh": "使用 `/runtime`、`/runtime inventory`、`/runtime mcp`、`/runtime health` 或 `/runtime recovery`。",
    },
    "channel_usage": {
        "en": "Use `/channel status [name]`, `/channel restart <name>`, or `/channel repair <name>`.",
        "zh": "使用 `/channel status [name]`、`/channel restart <name>` 或 `/channel repair <name>`。",
    },
    "channel_unavailable": {
        "en": "Channel manager is not available in this runtime.",
        "zh": "当前运行时没有可用的 channel manager。",
    },
    "channel_not_found": {
        "en": "Channel `{channel}` is not registered in this runtime.",
        "zh": "当前运行时没有注册渠道 `{channel}`。",
    },
    "channel_none_configured": {
        "en": "- no configured channels",
        "zh": "- 当前没有已配置的渠道",
    },
    "channel_status_all_header": {
        "en": "Configured channel status:",
        "zh": "已配置渠道状态：",
    },
    "channel_status_header": {
        "en": "Channel `{channel}` status:",
        "zh": "渠道 `{channel}` 状态：",
    },
    "channel_status_line": {
        "en": "- {channel}: enabled={enabled}, available={available}, running={running}, error={error}",
        "zh": "- {channel}：enabled={enabled}，available={available}，running={running}，error={error}",
    },
    "channel_restart_done": {
        "en": "Restarted `{channel}`. result={status}, running={running}",
        "zh": "已重启 `{channel}`。result={status}，running={running}",
    },
    "channel_restart_failed": {
        "en": "Failed to restart `{channel}`: {error}",
        "zh": "重启 `{channel}` 失败：{error}",
    },
    "channel_repair_done": {
        "en": "Repaired `{channel}`. status={status}, running={running}",
        "zh": "已修复 `{channel}`。status={status}，running={running}",
    },
    "channel_repair_failed": {
        "en": "Failed to repair `{channel}`: {error}",
        "zh": "修复 `{channel}` 失败：{error}",
    },
    "runtime_summary_header": {
        "en": "Runtime summary:",
        "zh": "运行时摘要：",
    },
    "runtime_inventory_summary": {
        "en": "- Inventory: mounted={mounted}/{total}, missing_prefixes={missing_prefixes}, binaries={installed}/{binary_total}, missing_binaries={missing_binaries}",
        "zh": "- Inventory：已挂载={mounted}/{total}，缺失前缀={missing_prefixes}，二进制={installed}/{binary_total}，缺失二进制={missing_binaries}",
    },
    "runtime_mcp_summary": {
        "en": "- MCP: connected={connected}, servers={servers}, registered_tools={tools}",
        "zh": "- MCP：已连接={connected}，servers={servers}，已注册工具={tools}",
    },
    "runtime_inventory_detail_header": {
        "en": "Runtime inventory detail:",
        "zh": "运行时 inventory 详情：",
    },
    "runtime_inventory_prefix_line": {
        "en": "- Prefix {path}: mounted={mounted}, fs={fs_type}, source={source}",
        "zh": "- 前缀 {path}：已挂载={mounted}，fs={fs_type}，source={source}",
    },
    "runtime_inventory_binary_line": {
        "en": "- Binary {name}: installed={installed}, command={command}, path={path}",
        "zh": "- 二进制 {name}：已安装={installed}，command={command}，路径={path}",
    },
    "runtime_mcp_detail_header": {
        "en": "MCP status detail:",
        "zh": "MCP 状态详情：",
    },
    "runtime_mcp_server_line": {
        "en": "- Server {name}: mode={mode}",
        "zh": "- Server {name}：模式={mode}",
    },
    "runtime_mcp_tool_line": {
        "en": "- Registered MCP tools: {tools}",
        "zh": "- 已注册 MCP 工具：{tools}",
    },
    "runtime_health_summary": {
        "en": "- Health: watchdog={watchdog}, stale_tasks={stale_tasks}, recent_errors={recent_errors}, soft_recoveries={soft}, hard_restarts={hard}, channel_running={running}/{total}, channel_blocked={blocked}",
        "zh": "- 健康：watchdog={watchdog}，卡住任务={stale_tasks}，近期错误={recent_errors}，软恢复={soft}，硬重启={hard}，运行中渠道={running}/{total}，阻塞渠道={blocked}",
    },
    "runtime_health_detail_header": {
        "en": "Runtime health detail:",
        "zh": "运行时健康详情：",
    },
    "runtime_health_channel_line": {
        "en": "- Channel {name}: enabled={enabled}, available={available}, running={running}, error={error}",
        "zh": "- 渠道 {name}：enabled={enabled}，available={available}，running={running}，error={error}",
    },
    "runtime_restart_summary": {
        "en": "- Restart state: status={status}, fields={fields}, requested_at={requested_at}, completed_at={completed_at}, last_result={result}",
        "zh": "- 重启状态：status={status}，fields={fields}，requested_at={requested_at}，completed_at={completed_at}，last_result={result}",
    },
    "runtime_recovery_header": {
        "en": "Runtime recovery pack:",
        "zh": "运行时恢复包：",
    },
    "runtime_recovery_task_line": {
        "en": "- Task {task_id}: status={status}, stage={stage}, next={action}, safe={safe}, reason={reason}",
        "zh": "- 任务 {task_id}：状态={status}，阶段={stage}，下一步={action}，可自动执行={safe}，原因={reason}",
    },
    "runtime_recovery_pairing_line": {
        "en": "- Pairing {channel}: approved={approved}, pending={pending}, owner={owner}",
        "zh": "- 配对 {channel}：approved={approved}，pending={pending}，owner={owner}",
    },
    "runtime_notice_submitted": {
        "en": "Runtime restart submitted. Planned restart fields: {fields}. I will report again when restart begins and when the runtime is healthy.",
        "zh": "运行时重启已提交。计划重启字段：{fields}。重启开始和恢复健康后我会继续汇报。",
    },
    "runtime_notice_restarting": {
        "en": "Runtime restart is now in progress. Fields: {fields}.",
        "zh": "运行时现在开始重启。字段：{fields}。",
    },
    "runtime_notice_healthy": {
        "en": "Runtime restart completed successfully. Current version: {version}.",
        "zh": "运行时重启已成功完成。当前版本：{version}。",
    },
    "runtime_notice_failed": {
        "en": "Runtime apply/restart failed. Errors: {errors}",
        "zh": "运行时应用/重启失败。错误：{errors}",
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
    "kb_retry_failed_done": {
        "en": "Retried failed knowledge ingests: updated={updated}, failed={failed}.",
        "zh": "已重试失败的知识入库：updated={updated}，failed={failed}。",
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
