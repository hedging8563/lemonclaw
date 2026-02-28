---
name: skill-installer
description: Install, list, and manage agent skills from skills.sh, GitHub repos, or local paths. Use when the user asks to install, search, update, or remove skills.
metadata: {"lemonclaw":{"emoji":"📦"}}
---

# Skill Installer

Install skills from skills.sh, GitHub, or local paths into LemonClaw's workspace.

## When to use

Use this skill when the user asks any of:
- "install a skill from ..."
- "add skill ..."
- "search for skills"
- "list my skills"
- "remove/uninstall a skill"

## Install from skills.sh

skills.sh URLs follow the format: `https://skills.sh/<owner>/<repo>/<skill-name>`

To install, convert the URL to a GitHub clone:

```bash
# 1. Clone the repo to a temp directory
REPO_DIR=$(mktemp -d)
git clone --depth 1 https://github.com/<owner>/<repo>.git "$REPO_DIR"

# 2. Copy the skill to workspace
SKILL_DIR=~/.lemonclaw/workspace/skills/<skill-name>
mkdir -p "$SKILL_DIR"
cp -r "$REPO_DIR/skills/<skill-name>/"* "$SKILL_DIR/"

# 3. Cleanup
rm -rf "$REPO_DIR"

# 4. Verify
cat "$SKILL_DIR/SKILL.md" | head -10
```

### Example

For `https://skills.sh/lwmxiaobei/yt-dlp-skill/yt-dlp`:
- owner = `lwmxiaobei`
- repo = `yt-dlp-skill`
- skill = `yt-dlp`

```bash
REPO_DIR=$(mktemp -d)
git clone --depth 1 https://github.com/lwmxiaobei/yt-dlp-skill.git "$REPO_DIR"
mkdir -p ~/.lemonclaw/workspace/skills/yt-dlp
cp -r "$REPO_DIR/skills/yt-dlp/"* ~/.lemonclaw/workspace/skills/yt-dlp/
rm -rf "$REPO_DIR"
```

## Install from GitHub URL

For direct GitHub repo URLs:

```bash
REPO_DIR=$(mktemp -d)
git clone --depth 1 <github-url> "$REPO_DIR"
# Find all skills in the repo
find "$REPO_DIR" -name "SKILL.md" -type f
# Copy desired skill directory to workspace
cp -r "$REPO_DIR/skills/<name>" ~/.lemonclaw/workspace/skills/<name>
rm -rf "$REPO_DIR"
```

## List installed skills

```bash
ls -la ~/.lemonclaw/workspace/skills/
```

Or check each skill's description:
```bash
for d in ~/.lemonclaw/workspace/skills/*/; do
  name=$(basename "$d")
  desc=$(head -5 "$d/SKILL.md" 2>/dev/null | grep "^description:" | cut -d: -f2-)
  echo "  $name: $desc"
done
```

## Remove a skill

```bash
rm -rf ~/.lemonclaw/workspace/skills/<skill-name>
```

## Notes

- Skills are directories containing a `SKILL.md` file.
- Install location: `~/.lemonclaw/workspace/skills/<skill-name>/`
- After install, remind the user to start a new session (`/new`) to load the skill.
- Workspace skills override built-in skills with the same name.
- Requires `git` for remote installs.
