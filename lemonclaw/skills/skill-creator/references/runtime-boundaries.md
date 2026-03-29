# LemonClaw Skill / Runtime Boundary

Use this reference when authoring or reviewing a LemonClaw skill.

## Put It In The Skill

Skills should own:

- trigger intent and non-trigger cases
- local heuristics
- parameter conventions
- checklists
- templates
- examples
- pointers to `references/`, `assets/`, and `scripts/`

## Put It In The Runtime

Do not rely on `SKILL.md` alone for:

- durable multi-step state
- resume / replay
- human confirmation checkpoints
- retry budgets
- side-effect ordering
- fail-closed enforcement
- task linkage across turns
- irreversible action gating

If the system must not skip a step, the runtime must enforce that rule.

## Pattern Mapping

- `tool-wrapper`: best when the agent needs expert usage notes for a tool or domain.
- `generator`: best when output must follow a stable template.
- `reviewer`: best when evaluation is driven by a checklist.
- `inversion`: best when the skill must gather missing context before acting.
- `pipeline`: best when steps are ordered, but only soft sequencing should live in the skill. Hard sequencing belongs in runtime/workflow code.
