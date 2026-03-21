---
name: scaffold-assemble
description: "Assemble scaffold interview state into canonical specs, rendered previews, audits, and optional auto-apply outputs"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
metadata:
  openclaw:
    emoji: "🛠️"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# Scaffold Assemble

Use this phase skill after the interview has enough information to build the target.

## Responsibilities

- assemble the canonical spec
- render previews into `compiler/generated/`
- validate the rendered output
- optionally auto-apply the runtime files
- generate audit and review artifacts

## Core Commands

```bash
clawscaffold render --id sales/coach
clawscaffold validate --id sales/coach
clawscaffold apply --id sales/coach
clawscaffold audit --id sales/coach --kind agent --behavioral
clawscaffold review
```

## Auto-Apply Rules

- Only use `--auto-apply` when the caller explicitly wants the full pipeline
- Respect the content preservation gate
- Write the review brief, transcript, and queue entry on successful completion

## Error Handling

- If schema validation or missing-field errors are interpretable, translate them into a corrective question for the operator
- If rendering or file IO fails in a non-recoverable way, stop and preserve the state file

## Outputs

- `catalog/<kind>s/<id>.yaml`
- `compiler/generated/<kind>s/<id>/`
- `compiler/runs/<run-id>/interview.json`
- `compiler/runs/<run-id>/audit-report.json` when audited
- `catalog/<kind>s/<id>.review.md` after audit
- `catalog/<kind>s/<id>.interview.json` after audit
- `compiler/review-queue.yaml` after audit
