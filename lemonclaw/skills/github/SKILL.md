---
name: github
description: Work with GitHub through the gh CLI. Use when the user wants to inspect pull requests, issues, workflow runs, CI failures, or GitHub metadata.
metadata: {"lemonclaw":{"emoji":"🐙","pattern":"tool-wrapper","requires":{"bins":["gh"]},"install":[{"id":"brew","kind":"brew","formula":"gh","bins":["gh"],"label":"Install GitHub CLI (brew)"},{"id":"apt","kind":"apt","package":"gh","bins":["gh"],"label":"Install GitHub CLI (apt)"}]}}
triggers: "github.com,pull request,issue,gh api,gh run,workflow runs,workflow run,CI status,仓库,github,提交pr,合并pr,pull-request"
---

# GitHub Skill

This is a `tool-wrapper` skill for the `gh` CLI.

## Entry Rule

Use this skill when the user wants GitHub data or actions:
- inspect a PR or issue
- read workflow runs or CI logs
- query repository metadata

Do not mutate GitHub state unless the user explicitly asks for a write action.

## Runtime Boundary

- Skill owns: `gh` command selection and output-shaping conventions.
- Runtime owns: longer workflows, approvals, retries, and task persistence.

## Inspect First

Prefer read-only inspection before acting:

```bash
gh pr view 55 --repo owner/repo
gh issue view 123 --repo owner/repo
gh run list --repo owner/repo --limit 10
```

If you are outside a git checkout, always pass `--repo owner/repo` or use the full GitHub URL.

## Structured Output

Prefer `--json` and `--jq` whenever the result will be parsed or summarized:

```bash
gh pr list --repo owner/repo --json number,title,state
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```

## Common Tasks

Check PR CI:
```bash
gh pr checks 55 --repo owner/repo
```

List workflow runs:
```bash
gh run list --repo owner/repo --limit 10
```

Inspect one run:
```bash
gh run view <run-id> --repo owner/repo
gh run view <run-id> --repo owner/repo --log-failed
```

Advanced query:
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## Guardrails

- Read first, then write.
- Prefer narrow queries over dumping large logs.
- When a write is requested, summarize the exact object being changed before acting.
