---
name: scaffold-interview-planner
description: Guide the scaffold interviewer through deterministic adopt interviews
  using planner tools.
version: 1.0.0
permissions:
  filesystem: none
  network: false
triggers:
- command: /scaffold-interview-planner
metadata:
  openclaw:
    emoji: ':compass:'
---

# Overview

<!-- oc:section id="overview" source="authored" checksum="dee1bac82f7a" generated="2026-03-13" -->
This skill keeps the scaffold interview conversational while the Python planner stays authoritative. Use it when the interviewer needs to analyze a target, surface decision bundles, ask one adaptive question at a time, accept recommendations, or finalize a reviewable draft.
<!-- /oc:section id="overview" -->

## Usage

<!-- oc:section id="usage" source="authored" checksum="47846e2db299" generated="2026-03-13" -->
Follow this loop:

1. Call `scaffold_analyze` with `mode=adopt`, the target kind/id, and the execution style.
2. Summarize imported sections, generated sections, flagged review items, depth mode, and whether the run can already finalize.
3. If `_026_config_findings` or `_026_decision_bundles` are present, frame them as coherent decisions rather than raw field diffs.
4. If the run is interactive, fetch exactly one question with `scaffold_next_question`.
5. Relay the planner's `structured_reason` when it materially helps trust or challenge the question.
6. Record the operator's answer with `scaffold_answer`.
7. Repeat until the planner has no remaining required questions, then call `scaffold_finalize`.

In non-interruptive mode, the operator may still inspect or override one generated section within the same run before finalizing. When the planner enters deep mode mid-run, announce that transition briefly before relaying the next live question.
<!-- /oc:section id="usage" -->

## Triggers

<!-- oc:section id="triggers" source="authored" checksum="e8f3da67c1a5" generated="2026-03-13" -->
- `/scaffold-interview-planner`
<!-- /oc:section id="triggers" -->

## Requirements

<!-- oc:section id="requirements" source="authored" checksum="9746b3ba6601" generated="2026-03-13" -->
- Preferred planner tools: `scaffold_analyze`, `scaffold_next_question`, `scaffold_answer`, `scaffold_finalize`
- Fallback when those tools are unavailable: `exec` with `clawscaffold interview-agent ...`
- Workspace access to the current repository through the planner's Python core
- No direct file mutations from the conversation layer
<!-- /oc:section id="requirements" -->

## Planner Contract

<!-- oc:section id="planner-contract" source="authored" checksum="374a71e4f330" generated="2026-03-13" -->
Treat the planner response as the single source of truth. Do not infer missing fields when the tool can answer them.
Always relay the exact `run_id` value from the planner payload. Do not rewrite it into a shorter or friendlier label.

Required response concepts:
- `run_id`
- `mode`
- `target`
- `execution_style`
- `summary`
- `recommendations`
- `safe_to_finalize`

Adopt-specific extensions:
- `_026_config_findings`
- `_026_depth_mode`
- `_026_decision_bundles`
- question-level `_026_structured_reason`, `_026_provenance_basis`, `_026_confidence_band`, `_026_blocking_level`
- answer-level `_026_intent_signals`

When the planner returns a question, ask only that question. If the question is a decision bundle, keep the framing strategic and concise. If it is a nonstandard gap, label it as a design prompt rather than a supported configuration field. When it returns no question, either finalize or explain the reviewable draft that already exists.

If the OpenClaw runtime did not inject the dedicated scaffold tools, use `exec` to invoke the CLI subcommands directly and continue using the CLI JSON output as the planner response.
<!-- /oc:section id="planner-contract" -->

## Response Contract

<!-- oc:section id="response-contract" source="authored" checksum="6def730c6dbf" generated="2026-03-13" -->
Default reply shape:

- one short summary paragraph or bullet block
- one explicit question or one explicit next step

For generated sections:
- show rationale first
- show full text automatically for low-confidence recommendations
- show full text on demand when the operator asks to inspect it

For question presentation:
- surface `structured_reason` for bundle questions, deep-mode prompts, and batch confirmations
- announce deep-mode transitions in one sentence before the next question
- show provenance when the planner marked a question or recommendation as low-confidence, inferred, exemplar-backed, or nonstandard
- treat exemplar comparison as advisory only; do not describe it as a requirement
- when a question is marked as a design prompt, say explicitly that the current schema does not support it

Never bury flagged review items after finalization. Surface them before you hand the operator the next CLI step.
<!-- /oc:section id="response-contract" -->

## Safety

<!-- oc:section id="safety" source="authored" checksum="aa89d7f05cce" generated="2026-03-13" -->
- Never write canonical YAML, rendered previews, or runtime files directly from conversation text.
- Never bypass planner resume warnings when the target drifted.
- Never treat generated recommendations as imported content.
- Finalize to a reviewable draft only. Downstream render, validate, apply, and rollback remain separate authoritative steps.
<!-- /oc:section id="safety" -->
