---
name: skill-installer
description: Install, list, update, or remove LemonClaw skills from skills.sh, GitHub repos, or local paths.
metadata: {"lemonclaw":{"emoji":"📦","pattern":"pipeline"}}
triggers: "安装skill,install skill,add skill,update skill,update an installed skill,upgrade skill,remove skill,remove a skill,uninstall skill,uninstall a skill,skills.sh,skill列表,list skills,search skills,搜索skill,GitHub repo,GitHub repos,local path"
---

# Skill Installer

This is a `pipeline` skill:
1. inspect the source
2. install or remove
3. verify the result

## Entry Rule

Use this skill when the user asks to:
- install a skill
- list installed skills
- remove or uninstall a skill
- install from `skills.sh`, GitHub, or a local path

## Runtime Boundary

- Skill owns: source parsing, install path conventions, and verification steps.
- Runtime owns: long-running retries and user approval for risky overwrites.

## Install Location

Workspace skills live at:

```text
~/.lemonclaw/workspace/skills/<skill-name>/
```

Workspace skills override built-in skills with the same name.

## Inspect Before Installing

### skills.sh

Format:

```text
https://skills.sh/<owner>/<repo>/<skill-name>
```

Prefer skills.sh when the user gives a marketplace URL.

### GitHub repo

If the skill name is not obvious, clone first and inspect:

```bash
REPO_DIR=$(mktemp -d) && git clone --depth 1 <github-url> "$REPO_DIR" && find "$REPO_DIR" -name SKILL.md -type f
```

## Install

From skills.sh:

```bash
REPO_DIR=$(mktemp -d) && git clone --depth 1 https://github.com/<owner>/<repo>.git "$REPO_DIR" && mkdir -p ~/.lemonclaw/workspace/skills/<skill-name> && cp -r "$REPO_DIR/skills/<skill-name>/"* ~/.lemonclaw/workspace/skills/<skill-name>/ && python3 -c "import shutil; shutil.rmtree('$REPO_DIR')" && echo "Installed <skill-name> successfully"
```

From GitHub:

```bash
REPO_DIR=$(mktemp -d) && git clone --depth 1 <github-url> "$REPO_DIR" && cp -r "$REPO_DIR/skills/<name>" ~/.lemonclaw/workspace/skills/<name> && python3 -c "import shutil; shutil.rmtree('$REPO_DIR')" && echo "Installed <name> successfully"
```

From local path:

```bash
mkdir -p ~/.lemonclaw/workspace/skills/<skill-name> && cp -r <local-skill-dir>/* ~/.lemonclaw/workspace/skills/<skill-name>/
```

## Verify

List installed skills:

```bash
ls -la ~/.lemonclaw/workspace/skills/
```

Check description quickly:

```bash
for d in ~/.lemonclaw/workspace/skills/*/; do
  name=$(basename "$d")
  desc=$(head -5 "$d/SKILL.md" 2>/dev/null | grep "^description:" | cut -d: -f2-)
  echo "  $name: $desc"
done
```

For local or edited skills, prefer validating with:

```bash
python3 lemonclaw/lemonclaw/skills/skill-creator/scripts/quick_validate.py <path/to/skill>
```

## Remove

```bash
python3 -c "import shutil; shutil.rmtree('$HOME/.lemonclaw/workspace/skills/<skill-name>')"
```

## Guardrails

- Do not overwrite an existing installed skill silently.
- Do not use `rm -rf`; use `python3` + `shutil.rmtree`.
- Built-in skills do not need installation.
