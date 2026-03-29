# Workflow Patterns

Use this file when the skill needs a repeatable execution flow.

## Primary Patterns

### Tool Wrapper

Use when the agent needs expert notes about a tool, API, or library.

Structure:
- When to trigger
- When not to trigger
- Inspect-first rules
- Safe defaults
- Verification after action

### Generator

Use when output must follow a stable template.

Structure:
- Minimum required inputs
- Template to load from `assets/`
- Output validation checklist
- Fallback when inputs are incomplete

### Reviewer

Use when quality is evaluated against a checklist.

Structure:
- Load checklist from `references/`
- Apply each rule
- Group findings by severity
- Suggest concrete fixes

### Inversion

Use when the skill must gather missing context before acting.

Structure:
- Ask only the missing questions
- Prefer one question at a time
- Stop once enough information is gathered
- Do not start irreversible work early

### Pipeline

Use when steps are ordered and each stage depends on the previous one.

Structure:
- Preconditions
- Ordered steps
- Verification after each stage
- Cleanup or handoff

Important:
- Soft sequencing can live in the skill
- Hard sequencing, retries, and checkpoints must be enforced by runtime/workflow code

## Reusable Subpatterns

### Decision Tree

Use when the first step is choosing among multiple valid paths.

### Inspect Then Act

Use when the skill must gather context before deciding.

### Safe Retry Loop

Describe retryable failures in the skill, but keep retry budgets and stop conditions in runtime when they affect correctness or side effects.

### Human Checkpoint

Skills may present the tradeoff, but runtime should own the irreversible gate when skipping confirmation is unacceptable.
