---
name: scaffold-interview-content
description: "Draft and refine scaffold interview content sections with accept, edit, or regenerate control"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
metadata:
  openclaw:
    emoji: "✍️"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# Scaffold Interview Content

Use this phase skill for the content pass of the scaffold interview.

## Responsibilities

- Ask one content question at a time
- Draft section content from the collected answers
- Present each draft for accept, edit, or regenerate
- Preserve source tracking: `imported` when kept, `authored` when changed

## Agent Content Goals

- `Who I Am`: first-person identity
- `Core Principles`: concrete, testable bullets
- `Boundaries`: explicit prohibitions
- `Communication Style`: concise operating voice
- `Security Rules`: standard prompt-injection block
- `Memory`: explicit memory behavior

## Skill Content Goals

- overview
- usage
- requirements
- command trigger alignment

## Flow

1. Collect identity inputs for create mode.
2. Reuse imported content for adopt mode unless the user changes it.
3. Use audit findings to target specific sections in extend mode.
4. After each section decision, persist the interview state immediately.

## CLI Command

```bash
clawscaffold interview --mode create --kind agent --id sales/coach
```

## Editing Rules

- `accept`: keep the presented draft as-is
- `edit`: replace the draft with operator-provided text
- `regenerate`: produce an alternative draft with the same facts and intent

## Guardrails

- Do not overwrite unrelated sections during extend mode
- Do not downgrade imported sections to generic boilerplate
- If the user input is too vague to draft safely, ask a narrower follow-up instead of inventing detail
