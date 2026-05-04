# ClawScaffold

Spec-first target lifecycle manager for OpenClaw agents, skills, and pipelines.

## Features

- **Interactive interviews** — guided create/adopt/extend workflows for agents, skills, and pipelines
- **Spec-first paradigm** — canonical YAML specs define targets; runtime artifacts are compiled output
- **8 audit checks** — automated readiness assessment before deployment
- **Pipeline registry** — track managed targets with lifecycle status
- **Dual-format skills** — 7 SKILL.md files for both OpenClaw and Claude Code
- **Plugin hooks** — abstract interfaces for governance, outbound gate, and MCP integrations

## Installation

```bash
pip install clawscaffold
```

With optional spec validation:
```bash
pip install clawscaffold[spec]
```

## Quick Start

```bash
# Initialize a project
clawscaffold init

# Create a new agent spec
clawscaffold create --name sales/coach --kind agent

# Adopt an existing agent
clawscaffold adopt --name sales/coach --source agents/sales/coach/SOUL.md --kind agent

# Audit a target
clawscaffold audit --name sales/coach

# Render spec to runtime files
clawscaffold render --id sales/coach
```

## Install Skills

```bash
# For Claude Code
./scripts/install-skills.sh claude-code

# For OpenClaw
./scripts/install-skills.sh openclaw
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize a clawscaffold project (creates .clawscaffold marker) |
| `create` | Create a new target spec |
| `adopt` | Adopt an existing runtime artifact into managed scope |
| `audit` | Run readiness checks against a target |
| `interview` | Start an interactive interview for target creation/adoption |
| `render` | Compile spec to runtime files |
| `validate` | Validate spec structure and content |
| `promote` | Promote a target to managed status |
| `enforce` | Enforce managed registry consistency |
| `install-skills` | Install SKILL.md files to Claude Code or OpenClaw |
| `sync-agents` | Register catalog agents with the OpenClaw gateway |
| `sync-skills` | Sync skills from repo into agent workspace directories |
| `sync` | Run sync-agents and sync-skills in one pass |

## Using with ClawSpec

[ClawSpec](https://github.com/austinmao/clawspec) is the contract-first QA framework for OpenClaw. When used together, ClawScaffold auto-generates ClawSpec test scenarios during adoption and creation workflows.

Install both:

```bash
pip install clawscaffold[spec]   # includes clawspec as optional dependency
```

When ClawSpec is installed, `clawscaffold adopt` and `clawscaffold create` automatically generate:
- `tests/scenarios.yaml` — smoke, negative, and identity test contracts
- `tests/handoffs/*.yaml` — handoff contracts for multi-agent delegation
- Coverage ledger entries for the adopted target

Without ClawSpec installed, these steps are skipped gracefully — the scaffolder works standalone for spec management and auditing.

```bash
# Adopt an agent — ClawSpec scenarios auto-generated
clawscaffold adopt --name sales/coach --source agents/sales/coach/SOUL.md --kind agent

# Verify the generated tests
clawspec validate agents/sales/coach
clawspec run agents/sales/coach --dry-run
```

## Related Projects

- **[ClawSpec](https://github.com/austinmao/clawspec)** — Contract-first QA for OpenClaw skills and agents (29 assertion types, Opik observability, regression baselines)
- **[ClawWrap](https://github.com/austinmao/clawwrap)** — Spec-first outbound message routing gate (policy enforcement, audit trail)
- **[OpenClaw](https://github.com/austinmao/openclaw)** — Local-first AI agent framework (LLM + chat channels + Markdown skills)

## Development

```bash
git clone https://github.com/austinmao/clawscaffold.git
cd clawscaffold
pip install -e ".[dev]"
pytest
```

## OpenClaw Gateway Plugin

ClawScaffold ships with a gateway plugin (scaffold-planner) that registers scaffold interview tools directly in the OpenClaw gateway. The plugin provides four tools: `scaffold_analyze`, `scaffold_next_question`, `scaffold_answer`, and `scaffold_finalize`.

### Installation

1. Copy the `extensions/scaffold-planner/` directory into your OpenClaw workspace:

```bash
cp -r extensions/scaffold-planner/ ~/.openclaw/extensions/scaffold-planner/
```

2. Register the plugin in your `~/.openclaw/openclaw.json`:

```json
{
  "extensions": {
    "scaffold-planner": {
      "repoRoot": "/path/to/your/workspace",
      "timeoutMs": 30000
    }
  }
}
```

3. Restart the gateway:

```bash
openclaw gateway restart
```

### Plugin Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `repoRoot` | string | `$OPENCLAW_WORKSPACE` or `cwd` | Workspace root containing the clawscaffold package |
| `pythonBin` | string | `python3` | Path to Python binary |
| `timeoutMs` | integer | `30000` | CLI execution timeout in milliseconds |

### Registered Tools

`scaffold_analyze`, `scaffold_next_question`, `scaffold_answer`, `scaffold_finalize`

See the [openclaw.plugin.json](extensions/scaffold-planner/openclaw.plugin.json) for the full config schema.

## ClawSuite

This package is part of **ClawSuite** — the OpenClaw agent infrastructure toolkit.

| Package | Description | Repo |
|---|---|---|
| **ClawPipe** | Config-driven pipeline orchestration | [austinmao/clawpipe](https://github.com/austinmao/clawpipe) |
| **ClawSpec** | Contract-first testing for skills & agents | [austinmao/clawspec](https://github.com/austinmao/clawspec) |
| **ClawWrap** | Outbound policy & conformance engine | [austinmao/clawwrap](https://github.com/austinmao/clawwrap) |
| **ClawAgentSkill** | Skill discovery, scanning & adoption | [austinmao/clawagentskill](https://github.com/austinmao/clawagentskill) |
| **ClawScaffold** | Agent/skill scaffold interviews | [austinmao/clawscaffold](https://github.com/austinmao/clawscaffold) |
| **ClawInterview** | Pipeline interview compilation & execution | *(coming soon)* |

All packages include OpenClaw gateway plugins for autonomous agent access.

## License

MIT
