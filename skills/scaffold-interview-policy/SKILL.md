---
name: scaffold-interview-policy
description: "Run the optional policy pass for scaffold interviews: memory, cognition, and channel defaults"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
metadata:
  openclaw:
    emoji: "⚙️"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# Scaffold Interview Policy

Use this phase skill when the content pass is complete and the operator wants to tune policy settings.

## Scope

- memory retrieval mode
- cognition complexity
- operator channels for agents

## Rules

- Prefer multiple choice with a recommended option
- Use inferred policy hints when available
- Keep the policy pass optional for normal create/adopt/extend runs
- Allow standalone invocation for existing specs

## CLI Commands

```bash
clawscaffold interview --id sales/coach --pass policy
clawscaffold interview --mode adopt --kind agent --id marketing/brand
```

## Defaults

- agents: `universal_file` memory, `medium` cognition, `slack` operator channel
- skills: `universal_file` memory, `low` cognition, no channels

## Output

Write updated policy values back into the interview state so `scaffold-assemble` can merge them into the canonical spec.
