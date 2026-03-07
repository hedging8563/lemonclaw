---
name: browser
description: Browser automation for AI agents. Use when the user needs to interact with websites, fill forms, click buttons, take screenshots, extract data, test web apps, or automate any browser task. Triggers on "open a website", "fill out a form", "click a button", "take a screenshot", "scrape data", "test this web app", "login to a site", or any browser interaction request.
metadata: {"lemonclaw":{"emoji":"🌐","os":["darwin","linux"],"requires":{"bins":["agent-browser"]}}}
---

# Browser Automation (agent-browser)

Use the `browser` tool for all web interaction. Pass the command string directly (without the `agent-browser` prefix).

## Core Workflow

Every browser automation follows this pattern:

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
- **Workspace restriction**: With `tools.restrict_to_workspace=true`, relative files used by
  `state save/load`, screenshots, and PDFs stay under the workspace directory

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
