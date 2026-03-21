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

## Development

```bash
git clone https://github.com/austinmao/clawscaffold.git
cd clawscaffold
pip install -e ".[dev]"
pytest
```

## License

MIT
