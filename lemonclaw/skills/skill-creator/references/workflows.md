# Workflow Patterns

Use this file when the skill needs a repeatable execution flow.

## Pattern 1: Decision Tree

Use when the first step is choosing among multiple valid paths.

Structure:
- State the input signals that determine the branch.
- Give a short rule for each branch.
- Link each branch to its detailed section or script.

## Pattern 2: Linear Procedure

Use when the task should happen in a strict order.

Structure:
- Preconditions
- Ordered steps
- Verification
- Cleanup or handoff

## Pattern 3: Inspect Then Act

Use when the skill must gather context before deciding.

Structure:
- Inspect files, APIs, or environment first.
- Summarize what matters.
- Choose the least risky action.
- Re-check the result after the action.

## Pattern 4: Safe Retry Loop

Use when external systems are flaky.

Structure:
- Define retryable failures.
- Set a retry budget.
- Record the last failure clearly.
- Stop and surface the blocker when the budget is exhausted.

## Pattern 5: Human Checkpoint

Use when there are non-obvious consequences.

Structure:
- Do all reversible preparation work first.
- Present the tradeoff in 1-2 sentences.
- Ask for confirmation only at the irreversible boundary.
