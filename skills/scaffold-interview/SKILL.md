---
name: scaffold-interview
description: "Guide create/adopt/extend scaffold interviews and persist interview state for resume or auto-apply"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
triggers:
  - command: /scaffold-interview
metadata:
  openclaw:
    emoji: "🧱"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# Scaffold Interview

Use this skill when a user wants to create a new scaffolded agent or skill, adopt an existing runtime file into the canonical spec system, or extend an existing scaffold target through a guided interview.

## Scope

- Route the user into one of three modes: `create`, `adopt`, or `extend`
- Collect only the next required answer, never a long questionnaire
- Persist every step to `compiler/runs/<run-id>/interview.json`
- Hand off specialized work to the phase skills instead of duplicating it

## Entry Rules

1. If the user already named a target like `sales/coach`, preserve it.
2. If no target was given and the current directory is inside `agents/` or `skills/`, infer the target and confirm it.
3. If there is an unfinished run for the same target, offer resume before starting a fresh run.
4. If the user asked for policy-only tuning, jump directly to the policy phase.

## Phase Routing

- `create`: use `scaffold-interview-content`, then optionally `scaffold-interview-policy`, then `scaffold-assemble`
- `adopt`: use `scaffold-extract`, confirm imported sections, optionally use `scaffold-interview-policy`, then `scaffold-assemble`
- `extend`: use `scaffold-extract` for audit, ask which sections to improve, use `scaffold-interview-content`, optionally `scaffold-interview-policy`, then `scaffold-assemble`

## Command Mapping

For CLI-first execution, prefer these commands:

```bash
clawscaffold interview-agent analyze --mode adopt --kind skill --id marketing/brand-standards
clawscaffold interview-agent next-question --run-id <run-id>
clawscaffold interview-agent answer --run-id <run-id> --question-id <question-id> --choice accept
clawscaffold interview-agent finalize --run-id <run-id>
clawscaffold interview --mode create --kind agent --id sales/coach
clawscaffold interview --mode adopt --kind agent --id marketing/brand
clawscaffold interview --mode extend --kind skill --id marketing/newsletter-qa
clawscaffold interview --resume <run-id>
clawscaffold interview --id sales/coach --pass policy
clawscaffold interview --mode create --kind agent --id sales/coach --auto-apply
```

## Conversation Rules

- One question at a time
- Multiple choice when a reasonable default exists
- For generated drafts, present the draft and ask: accept, edit, or regenerate
- Do not silently discard imported content; confirmations must preserve the source decision
- Keep status updates terse and concrete

## State Expectations

Interview state must capture:

- `run_id`
- `mode`
- `target_kind`
- `target_id`
- `builder_identity`
- section map with source tracking
- policy hints
- ordered questions
- answers
- current index
- pass number
- content hash for resume drift detection

## Outputs

Minimum successful outputs:

- canonical spec in `catalog/`
- rendered preview in `compiler/generated/`
- interview state in `compiler/runs/`

When `--auto-apply` is used, also require:

- runtime files written under `agents/` or `skills/`
- audit report in `compiler/runs/<run-id>/audit-report.json`
- review brief in `catalog/<kind>s/<id>.review.md`
- transcript in `catalog/<kind>s/<id>.interview.json`
- queue entry in `compiler/review-queue.yaml`

## Safety

- Never apply runtime changes directly from the skill text; use the Python CLI
- If content preservation falls below the apply threshold, stop and surface the failure
- Preserve state on errors so the run can be resumed
- In OpenClaw-hosted runs, prefer the dedicated scaffold planner tools. If the runtime does not inject them, fall back to `exec` + `clawscaffold interview-agent ...` and keep using the CLI JSON output as the source of truth.

## Claude Code

When invoked from Claude Code, this skill is instructional only. Use the generated `.claude/skills/` wrapper plus the Python CLI for execution.
