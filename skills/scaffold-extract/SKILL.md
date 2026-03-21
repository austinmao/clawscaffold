---
name: scaffold-extract
description: "Parse runtime files, infer policy hints, and run structural or heuristic audits for scaffold interview flows"
version: "1.0.0"
permissions:
  filesystem: write
  network: false
metadata:
  openclaw:
    emoji: "🧩"
    requires:
      bins: ["python3"]
      env: []
      os: ["darwin", "linux"]
---

# Scaffold Extract

Use this phase skill when the interview needs structured context from an existing runtime file.

## Responsibilities

- Parse `SOUL.md` files by top-level `#` headings
- Parse `SKILL.md` files by YAML frontmatter plus `##` body headings
- Preserve section order, headings, and source metadata
- Infer policy hints from section content
- Run structural, heuristic, and cross-reference audits when extending an existing target

## Inputs

- target kind: `agent` or `skill`
- target id
- runtime path
- current repo root

## Outputs

- parsed sections
- inferred policy hints
- audit summary for extend mode

## CLI Commands

```bash
clawscaffold adopt --path agents/marketing/brand/SOUL.md
clawscaffold audit --id marketing/brand --kind agent
clawscaffold audit --id marketing/newsletter-qa --kind skill --behavioral
```

## Working Rules

- Never reduce the runtime file to headings only
- Preserve custom headings as custom sections
- Treat skill references and memory paths as cross-reference candidates
- Flag vague boundary language instead of silently accepting it

## Hand-off

Pass the parsed sections and policy hints to `scaffold-interview-content` or `scaffold-interview-policy` depending on the next phase.
