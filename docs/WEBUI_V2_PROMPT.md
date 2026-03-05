# LemonClaw WebUI v2 重构 — Gemini CLI Prompt

> 给 Gemini CLI 的完整上下文和指令

## 项目背景

LemonClaw 是一个基于 Python 的 AI Agent 平台（MIT 开源），当前 WebUI 是一个 3182 行的单文件 Preact SPA (`lemonclaw/gateway/webui/static/index.html`)，所有 JS/CSS/HTML 混在一起，无法维护。

需要将其重构为 Vite + Preact 的现代前端工程，实现 mochat 风格的三栏布局。

## 关键约束

1. **技术栈: Preact，不是 React** — 现有代码全部基于 Preact (htm/preact)，保持一致。Preact 兼容 React API 但只有 3KB。
2. **后端零改动** — 所有 API 已经就绪，前端直接请求 `http://localhost:18789/api/*`。API 完整文档见 `docs/API_CONTRACT.md`。
3. **暗色主题优先** — mochat.io 风格的开发者暗色美学。
4. **渐进式迁移** — 先跑通基础框架，再逐模块迁移功能。

## 目录结构

```
lemonclaw/
├── gateway/webui/
│   ├── static/index.html          # 现有 3182 行单文件 SPA (参考，不修改)
│   ├── webui-v2/                  # 新前端工程 (在这里创建)
│   │   ├── index.html
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── main.tsx
│   │       ├── App.tsx
│   │       ├── api/               # API 客户端
│   │       │   └── client.ts      # fetch wrapper + auth + SSE
│   │       ├── stores/            # 状态管理 (preact/signals)
│   │       │   ├── auth.ts
│   │       │   ├── sessions.ts
│   │       │   └── chat.ts
│   │       ├── components/
│   │       │   ├── layout/
│   │       │   │   ├── Sidebar.tsx        # 左栏: session 列表 + 导航
│   │       │   │   ├── ChatArea.tsx       # 中栏: 对话流
│   │       │   │   └── Inspector.tsx      # 右栏: 可折叠侧边栏
│   │       │   ├── chat/
│   │       │   │   ├── MessageList.tsx
│   │       │   │   ├── MessageInput.tsx
│   │       │   │   ├── ThinkingBlock.tsx
│   │       │   │   └── ToolDetail.tsx
│   │       │   ├── sidebar/
│   │       │   │   ├── SessionList.tsx
│   │       │   │   └── SessionItem.tsx
│   │       │   ├── inspector/
│   │       │   │   ├── StarOffice.tsx     # 像素办公室
│   │       │   │   ├── ConductorPanel.tsx
│   │       │   │   ├── MemoryPanel.tsx
│   │       │   │   └── McpPanel.tsx
│   │       │   ├── settings/
│   │       │   │   └── SettingsModal.tsx
│   │       │   └── auth/
│   │       │       └── LoginScreen.tsx
│   │       └── styles/
│   │           └── global.css
│   ├── routes.py                  # 后端 API (不动)
│   ├── settings.py                # Settings API (不动)
│   ├── activity.py                # Activity Feed API (不动)
│   └── conductor.py               # Conductor API (不动)
```

## 执行步骤

### Step 1: 工程初始化

在 `lemonclaw/gateway/webui/webui-v2/` 下创建 Vite + Preact + TypeScript 工程。

```bash
# 依赖
preact, @preact/signals, htm
# Dev 依赖
vite, @preact/preset-vite, typescript
```

`vite.config.ts` 配置 proxy 到后端:
```ts
server: {
  port: 5173,
  proxy: {
    '/api': 'http://localhost:18789',
    '/ws': { target: 'ws://localhost:18789', ws: true },
    '/health': 'http://localhost:18789',
  }
}
```

### Step 2: API 客户端 (`src/api/client.ts`)

参考 `docs/API_CONTRACT.md`，实现:
- `apiFetch(path, options)` — 统一 fetch wrapper，自动处理 401 跳转登录
- `chatStream(params)` — SSE 流式请求，返回 AsyncGenerator
- `wsConnect(path)` — WebSocket 连接 (Activity Feed)

认证方式: Cookie (`lc_session`)，由 `POST /api/auth` 设置，前端不需要手动管理。

### Step 3: 状态管理 (`src/stores/`)

使用 `@preact/signals` 做轻量状态管理:
- `auth.ts`: `isAuthenticated`, `authRequired`, `login()`, `logout()`, `checkAuth()`
- `sessions.ts`: `sessions`, `activeSessionKey`, `loadSessions()`, `createSession()`, `deleteSession()`
- `chat.ts`: `messages`, `isStreaming`, `sendMessage()`, `loadHistory()`

### Step 4: 三栏布局

```
┌──────────┬────────────────────────┬──────────────┐
│          │                        │              │
│  Sidebar │      Chat Area         │  Inspector   │
│  (240px) │      (flex: 1)         │  (320px)     │
│          │                        │  可折叠       │
│ Sessions │  Message List           │              │
│ 列表     │  + Input               │ StarOffice   │
│          │                        │ Conductor    │
│ 导航     │                        │ Memory       │
│          │                        │ MCP          │
└──────────┴────────────────────────┴──────────────┘
```

- 左栏 (Sidebar): 细长导航栏，session 列表 + 新建按钮 + 设置入口
- 中栏 (ChatArea): 纯净对话流，无气泡样式，monospace 代码块
- 右栏 (Inspector): 可折叠侧边栏抽屉，包含像素办公室、Conductor、Memory、MCP 面板

### Step 5: 逐模块迁移

按以下顺序从 `index.html` 迁移功能:

1. **Auth** — 登录界面 + cookie 认证
2. **Session 列表** — 左栏 session CRUD
3. **Chat 对话流** — SSE streaming + 消息渲染 (markdown, 代码块, thinking blocks)
4. **消息输入** — 文本输入 + 文件上传 + 快捷键 (Ctrl+Enter 发送)
5. **Model 选择** — per-session 模型切换
6. **Settings** — 模态框，读写配置
7. **Inspector 面板** — StarOffice + Conductor + Memory + MCP
8. **Activity Feed** — WebSocket 实时事件

### Step 6: 构建产物集成

最终 `vite build` 输出到 `dist/`，后端 `routes.py` 改为 serve `dist/index.html`。
但这一步先不做 — 开发阶段用 Vite dev server + proxy 联调。

## 设计规范

### 颜色

```css
--bg-primary: #0d1117;      /* 主背景 */
--bg-secondary: #161b22;    /* 侧边栏/卡片 */
--bg-tertiary: #21262d;     /* 输入框/hover */
--text-primary: #e6edf3;    /* 主文字 */
--text-secondary: #8b949e;  /* 次要文字 */
--accent: #58a6ff;          /* 强调色 */
--accent-green: #3fb950;    /* 成功/在线 */
--accent-red: #f85149;      /* 错误/离线 */
--border: #30363d;          /* 边框 */
```

### 字体

```css
--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-mono: "JetBrains Mono", "Fira Code", "SF Mono", monospace;
```

### 规则

- 状态标签用 monospace 字体
- 代码块用终端风格 (暗色背景 + 绿色/白色文字)
- Session 列表用卡片式，不是纯文字列表
- 无气泡样式对话 — user/assistant 消息用左对齐 + 角色标签区分
- 像素办公室 canvas 保持原有渲染逻辑

## 参考文件

- **API 文档**: `docs/API_CONTRACT.md` (完整的请求/响应格式)
- **现有 SPA**: `gateway/webui/static/index.html` (功能参考，不要复制代码风格)
- **后端路由**: `gateway/webui/routes.py`, `settings.py`, `activity.py`, `conductor.py`

## 注意事项

1. 不要修改任何 Python 后端文件
2. 不要使用 React，用 Preact
3. 不要用 CSS-in-JS，用普通 CSS 或 CSS Modules
4. SSE 解析要处理所有 6 种事件类型 (content/thinking/tool_hint/tool_start/tool_result/done/error)
5. WebSocket 要处理 30s 心跳 ping
6. 敏感字段 (api_key 等) 在 Settings 中显示掩码值，提交时如果值包含 `****` 后端会自动保留原值
7. session_key 强制 `webui:` 前缀
8. 像素办公室 (StarOffice) 的 canvas 渲染逻辑从 index.html 中提取，它是纯 JS 画的像素动画
