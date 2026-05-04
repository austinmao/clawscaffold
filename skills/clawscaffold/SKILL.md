---
name: clawscaffold
description: "Create, adopt, or extend agents and skills via scaffold CLI / run governance audit"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
triggers:
  - command: /scaffold
metadata:
  openclaw:
    emoji: "🏗️"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# ClawScaffold CLI (Non-Interactive)

Use this skill to create, adopt, or extend agents and skills through the spec-first scaffolder and run governance audits — all without interactive prompts.

## 1. Create a New Agent

```bash
clawscaffold interview --mode create --kind agent --id <domain/name> --auto-apply
```

Generates a default canonical spec, runs the interview with recommended defaults, renders runtime files, and applies them atomically.

## 2. Adopt an Existing Agent

```bash
clawscaffold interview --mode adopt --kind agent --id <domain/name> --auto-apply
```

Reads the existing `agents/<domain>/<name>/SOUL.md`, extracts sections into a canonical spec, and promotes the target to `managed` status in the adoption registry.

## 3. Create a New Skill

```bash
clawscaffold interview --mode create --kind skill --id <path/to/skill> --auto-apply
```

Generates a default skill spec with frontmatter schema, renders SKILL.md, and writes it to the workspace.

## 4. Adopt an Existing Skill

```bash
clawscaffold interview --mode adopt --kind skill --id <path/to/skill> --auto-apply
```

Reads the existing `skills/<path>/SKILL.md`, extracts metadata and sections into a canonical spec, and registers the target as `managed`.

## 5. Run Governance Audit

```bash
clawscaffold governance-audit
```

Validates all managed targets against structural rules (required SOUL.md sections, SKILL.md frontmatter, section marker integrity). Prints errors and warnings. Exits 0 on pass, 1 on failure.

## Key Concepts

### Cognition Posture

Canonical specs reference cognition by posture key, never by model name. The mapping lives in `tenants/ceremonia/cognition-registry.yaml`:

| Posture key | Resolved model |
|---|---|
| `low/economy/low` | gemini-2.5-flash-lite |
| `medium/standard/low` | claude-sonnet-4-6 |
| `high/premium/critical` | claude-opus-4-6 |

Policy fields `policy.cognition.complexity`, `cost_posture`, and `risk_posture` combine to select the posture key. Never hardcode model names like `opus` or `sonnet` in specs.

### File Layout

| Artifact | Path |
|---|---|
| Canonical spec | `catalog/agents/<id>.yaml` or `catalog/skills/<id>.yaml` |
| Rendered preview | `compiler/generated/agents/<id>/` or `compiler/generated/skills/<id>/` |
| Interview state | `compiler/runs/<run-id>/interview.json` |
| Audit report | `compiler/runs/<run-id>/audit-report.json` |
| Review brief | `catalog/<kind>s/<id>.review.md` |
| Adoption registry | `compiler/ownership/adoption-registry.json` |

### Adoption Registry

Tracks every runtime file with one of three statuses:
- `untracked` — exists at runtime but not managed by the compiler
- `draft` — canonical spec exists but not yet applied
- `managed` — compiler owns the runtime files; direct edits are blocked by the spec-managed guard hook

## Output

On success, the CLI prints:
```
[scaffold interview] run-id: <run-id>
[scaffold interview] spec: <path-to-canonical-spec>
[scaffold interview] review: <path-to-review-brief>
```

Governance audit prints `governance-audit: PASSED` or `governance-audit: FAILED (N errors)`.

## Error Handling

- If `python3` is not available, the skill will not load (gated by `requires.bins`).
- If a concurrent compiler run is in progress, the CLI rejects with a lock error (`compiler/.lock`). Wait and retry.
- If `--auto-apply` detects content preservation below threshold, or any failure occurs, state is saved to `compiler/runs/<run-id>/interview.json` for resume via `--resume <run-id>`.
