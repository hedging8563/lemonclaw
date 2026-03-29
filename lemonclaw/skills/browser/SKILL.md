---
name: browser
description: Browser automation for AI agents. Use when the user needs to interact with websites, fill forms, click buttons, take screenshots, extract data, test web apps, or automate any browser task. Triggers on "open a website", "fill out a form", "click a button", "take a screenshot", "scrape data", "test this web app", "login to a site", or any browser interaction request.
metadata: {"lemonclaw":{"emoji":"🌐","pattern":"tool-wrapper","os":["darwin","linux"],"requires":{"bins":["agent-browser"]}}}
triggers: "打开网页,浏览器,截图,网页截图,填表,填表单,fill out a form,点击按钮,click a button,爬取,scrape,screenshot,open website,open a website,browse,自动化测试,取屏幕截图,take a screenshot,抓取数据,scrape data,登录网站,login to a site,测试网页,test web app"
---

# Browser Automation (agent-browser + DICloak)

Use the `browser` tool for all web interaction. Pass the command string directly (without the `agent-browser` prefix).

This is a `tool-wrapper` skill. Let the browser tool own browser state and session state. Do not invent extra browser workflow state inside the skill.

There are two execution modes:

- **Normal browser mode**: default for ordinary browsing, forms, screenshots, scraping, and testing.
- **DICloak profile mode**: only when the task explicitly needs a leased browser profile or persistent login state.

Do **not** invent a separate DICloak tool. DICloak is accessed through explicit `browser` commands:

```text
browser: dicloak list_profiles
browser: dicloak open_profile <profile_id>
browser: open https://example.com
browser: snapshot -i
browser: click @e1
browser: dicloak close_profile
```

## When to Use Normal Browser vs DICloak

Use **normal browser mode** for:

- Opening public websites
- Filling forms that do not require a persisted identity
- Taking screenshots or PDFs
- Extracting data from pages
- Testing ordinary web flows

Use **DICloak** only for:

- Reusing a persistent login/profile state
- Working inside a specific leased browser profile
- Tasks that explicitly mention DICloak, profile lease, or long-lived authenticated browser identity

Do **not** use DICloak just because a site has a login page. Start with the normal browser unless the task clearly requires an existing profile.

## Runtime Boundary

- Skill owns: command patterns, DICloak selection rules, ref lifecycle guidance.
- Runtime owns: profile lease state, browser session state, retries, and delivery of screenshots/artifacts.

## Core Workflow

Every normal browser automation follows this pattern:

1. **Navigate**: `open https://example.com`
2. **Snapshot**: `snapshot -i` (get element refs like `@e1`, `@e2`)
3. **Interact**: Use refs to click, fill, select
4. **Re-snapshot**: After navigation or DOM changes, get fresh refs

```
browser: open https://example.com/form
browser: snapshot -i
# Output: @e1 [input type="email"], @e2 [input type="password"], @e3 [button] "Submit"

browser: fill @e1 "user@example.com"
browser: fill @e2 "password123"
browser: click @e3
browser: wait --load networkidle
browser: snapshot -i
```

## DICloak Workflow

When DICloak is required, use this exact shape:

1. **Inspect available profiles**
   - `browser: dicloak list_profiles`
2. **Open the chosen profile**
   - `browser: dicloak open_profile <profile_id>`
3. **Run ordinary browser commands in the same session**
   - `browser: open https://target.site`
   - `browser: snapshot -i`
   - `browser: click @e1`
4. **Close the profile when done**
   - `browser: dicloak close_profile`

Important:

- After `dicloak open_profile`, continue with **normal** browser commands. Do not prefix every command with `dicloak`.
- Keep the work in the same agent session so the leased profile stays attached to the same browser session name.
- Always close the leased profile when the task is done unless the user explicitly wants it kept open.

Example:

```text
browser: dicloak list_profiles
browser: dicloak open_profile 123456
browser: open https://app.example.com/dashboard
browser: wait --load networkidle
browser: snapshot -i
browser: click @e4
browser: dicloak close_profile 123456
```

## Command Chaining

Commands can be chained with `&&`, `||`, or `;` in a single browser tool call:

```
browser: open https://example.com && wait --load networkidle && snapshot -i
browser: fill @e1 "user@example.com" && fill @e2 "password" && click @e3
```

Chain when you don't need intermediate output. Run separately when you need to parse snapshot refs first.

## Essential Commands

```bash
# Navigation
open <url>              # Navigate to URL
close                   # Close browser session

# Snapshot (always do this after navigation)
snapshot -i             # Interactive elements with refs (recommended)
snapshot -i -C          # Include cursor-interactive elements
snapshot -s "#selector" # Scope to CSS selector

# Interaction (use @refs from snapshot)
click @e1               # Click element
fill @e2 "text"         # Clear and type text
type @e2 "text"         # Type without clearing
select @e1 "option"     # Select dropdown option
check @e1               # Check checkbox
press Enter             # Press key
scroll down 500         # Scroll page

# Get information
get text @e1            # Get element text
get url                 # Get current URL
get title               # Get page title

# Wait
wait @e1                # Wait for element
wait --load networkidle # Wait for network idle
wait --url "**/page"    # Wait for URL pattern
wait 2000               # Wait milliseconds

# Capture
screenshot              # Screenshot to temp dir
screenshot --full       # Full page screenshot
screenshot --annotate   # Annotated with numbered element labels
pdf output.pdf          # Save as PDF

# Diff
diff snapshot           # Compare current vs last snapshot
diff screenshot --baseline before.png  # Visual pixel diff
```

## Common Patterns

### Form Submission

```
browser: open https://example.com/signup
browser: snapshot -i
browser: fill @e1 "Jane Doe"
browser: fill @e2 "jane@example.com"
browser: select @e3 "California"
browser: check @e4
browser: click @e5
browser: wait --load networkidle
```

### Authentication with State Persistence

For ordinary browser state files:

```
browser: open https://app.example.com/login
browser: snapshot -i
browser: fill @e1 "username"
browser: fill @e2 "password"
browser: click @e3
browser: wait --url "**/dashboard"
browser: state save auth.json

# Reuse in future sessions
browser: state load auth.json
browser: open https://app.example.com/dashboard
```

If the task instead requires an existing DICloak profile, prefer DICloak over browser `state save/load`.

### Data Extraction

```
browser: open https://example.com/products
browser: snapshot -i
browser: get text @e5
browser: get text body
write_file: path="browser/page.txt", content="...captured text..."
```

### Annotated Screenshots (Vision Mode)

```
browser: screenshot --annotate
# Output includes image path and legend:
#   [1] @e1 button "Submit"
#   [2] @e2 link "Home"
browser: click @e2
```

### JavaScript Evaluation

```
browser: eval 'document.title'
browser: eval 'document.querySelectorAll("img").length'
```

Do not use shell redirection, pipes, or heredocs in browser commands. The browser tool
executes `agent-browser` directly without a shell; if you need to persist output, use
the filesystem tools.

## Ref Lifecycle (Important)

Refs (`@e1`, `@e2`, etc.) are invalidated when the page changes. Always re-snapshot after:

- Clicking links or buttons that navigate
- Form submissions
- Dynamic content loading (dropdowns, modals)

```
browser: click @e5        # Navigates to new page
browser: snapshot -i      # MUST re-snapshot
browser: click @e1        # Use new refs
```

## Security

- **Domain allowlist**: Configure `tools.browser.allowed_domains` to restrict navigation
- **Content boundaries**: Enabled by default, wraps page output in markers to prevent prompt injection
- **Output limits**: Configure `tools.browser.max_output` to prevent context flooding
- **Default file paths**: Relative files used by `state save/load`, screenshots, and PDFs resolve from the current workspace by default.
- **DICloak lease hygiene**: Open a profile only when needed, keep work in one session, and close it afterwards.

## DICloak Commands

Supported DICloak browser commands:

```text
dicloak list_profiles
dicloak open_profile <profile_id>
dicloak close_profile [profile_id]
```

Rules:

- `list_profiles` is read-only and safe as the first step.
- `open_profile` is stateful: it leases a profile and connects `agent-browser` to the returned debug port.
- `close_profile` releases the lease for the current session. If no explicit `profile_id` is passed, it closes the currently leased profile for that session.
- If `open_profile` fails with a kernel/browser runtime error, stop and report the concrete DICloak error instead of retrying blindly.

## Configuration

Set in LemonClaw config (`config.json` → `tools.browser`):

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable browser tool |
| `timeout` | `60` | Command timeout (seconds) |
| `allowed_domains` | `[]` | Domain allowlist (empty = no restriction) |
| `session_name` | `""` | Fixed session name (empty = auto) |
| `headed` | `false` | Show browser window |
| `content_boundaries` | `true` | Wrap output in content boundary markers |
| `max_output` | `50000` | Output truncation limit (chars) |
