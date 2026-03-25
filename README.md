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

## OpenClaw Suite

Part of the OpenClaw open-source toolchain:

| Package | Description | Repo |
|---------|-------------|------|
| **ClawPipe** | Config-driven pipeline orchestration engine | [austinmao/clawpipe](https://github.com/austinmao/clawpipe) |
| **ClawSpec** | Contract-first QA for skills and agents | [austinmao/clawspec](https://github.com/austinmao/clawspec) |
| **ClawWrap** | Outbound message routing and policy enforcement | [austinmao/clawwrap](https://github.com/austinmao/clawwrap) |
| **ClawAgentSkill** | Agent and skill discovery, security scanning | [austinmao/clawagentskill](https://github.com/austinmao/clawagentskill) |
| **ClawScaffold** | Agent and skill scaffolding and lifecycle management | [austinmao/clawscaffold](https://github.com/austinmao/clawscaffold) |

## License

MIT
