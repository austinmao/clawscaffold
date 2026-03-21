"""CLI commands for the pipeline scaffolder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clawscaffold.scaffold import registry, spec_generator, spec_parser, auditor
from clawscaffold.scaffold.adapters import lobster as lobster_adapter


def cmd_adopt(args: argparse.Namespace) -> int:
    """Adopt an existing pipeline into the scaffolder registry."""
    name = args.name
    source = args.source
    kind = args.kind

    if kind != "pipeline":
        print(f"Only 'pipeline' kind is supported. Got: {kind}", file=sys.stderr)
        return 1

    # Check source exists
    if not Path(source).exists():
        print(f"Source file not found: {source}", file=sys.stderr)
        return 1

    # Check not already adopted
    existing = registry.get_target(name, kind, args.registry_path)
    if existing:
        print(f"Already adopted: {kind}/{name}", file=sys.stderr)
        return 1

    # Parse and generate spec
    try:
        spec_path = spec_generator.write_spec(name, source)
    except (ValueError, FileNotFoundError) as e:
        print(f"Failed to parse source: {e}", file=sys.stderr)
        return 1

    # Register
    entry = registry.add_target(
        name=name,
        kind=kind,
        spec_path=str(spec_path),
        runtime_path=source,
        registry_path=args.registry_path,
    )

    print(f"Adopted: {kind}/{name}")
    print(f"  Spec: {spec_path}")
    print(f"  Registry: {args.registry_path}")
    print(f"  Status: {entry['status']}")
    print(f"\nRun 'scaffold audit --name {name}' to check what's missing.")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Audit a managed pipeline against requirements."""
    name = args.name
    kind = "pipeline"

    target = registry.get_target(name, kind, args.registry_path)
    if not target:
        print(f"Unknown pipeline: {name}", file=sys.stderr)
        return 1

    spec_path = target["spec_path"]
    try:
        spec = spec_parser.parse_spec(spec_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Failed to parse spec: {e}", file=sys.stderr)
        return 1

    report = auditor.audit_pipeline(spec)

    # Update last_audit
    from datetime import datetime, timezone
    registry.update_field(name, kind, "last_audit", datetime.now(timezone.utc).isoformat(), args.registry_path)

    # Print report
    print(f"Audit: pipeline/{name}")
    print(f"  Status: {target['status']}")
    print()

    has_issues = False
    for severity in ("required", "recommended", "optional"):
        items = report.get(severity, [])
        if items:
            has_issues = True
            print(f"  [{severity.upper()}]")
            for item in items:
                print(f"    - {item}")
            print()

    if not has_issues:
        print("  All checks passed.")
        return 0

    return 1 if report.get("required") else 0


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new pipeline from the canonical template."""
    name = args.name
    kind = args.kind

    if kind != "pipeline":
        print(f"Only 'pipeline' kind is supported. Got: {kind}", file=sys.stderr)
        return 1

    existing = registry.get_target(name, kind, args.registry_path)
    if existing:
        print(f"Already exists: {kind}/{name}", file=sys.stderr)
        return 1

    # Generate canonical 8-stage spec
    canonical_stages = [
        {"id": "generate", "agent": "unknown", "type": "content-generation"},
        {"id": "render", "agent": "unknown", "type": "deterministic-build"},
        {"id": "verify", "agent": "script:verify", "type": "verification"},
        {"id": "brand-gate", "agent": "unknown", "verdict": "required"},
        {"id": "approval", "agent": "human-gate", "type": "human-gate"},
        {"id": "publish", "agent": "script:publish", "type": "publication"},
        {"id": "record-create", "agent": "script:record-create"},
        {"id": "post-audit", "agent": "script:audit", "type": "certification"},
    ]

    spec_text = spec_generator.generate_spec(
        name,
        canonical_stages,
        f"workflows/{name}.lobster",
    )

    output_dir = Path(f"targets/pipeline/{name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    spec_path = output_dir / "spec.md"
    spec_path.write_text(spec_text)

    # Generate stub .lobster file via adapter
    lobster_path = Path(f"workflows/{name}.lobster")
    lobster_content = lobster_adapter.generate_lobster(canonical_stages, name)
    lobster_path.parent.mkdir(parents=True, exist_ok=True)
    lobster_path.write_text(lobster_content)

    # Register
    registry.add_target(
        name=name,
        kind=kind,
        spec_path=str(spec_path),
        runtime_path=str(lobster_path),
        registry_path=args.registry_path,
    )

    print(f"Created: {kind}/{name}")
    print(f"  Spec: {spec_path}")
    print(f"  Workflow: {lobster_path}")
    print(f"\nEdit the spec to customize stages, then run 'scaffold apply --name {name}'.")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply a pipeline spec to generate/update runtime files."""
    name = args.name
    kind = "pipeline"
    force = args.force

    target = registry.get_target(name, kind, args.registry_path)
    if not target:
        print(f"Unknown pipeline: {name}", file=sys.stderr)
        return 1

    spec_path = target["spec_path"]
    runtime_path = Path(target["runtime_path"])

    try:
        spec = spec_parser.parse_spec(spec_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Failed to parse spec: {e}", file=sys.stderr)
        return 1

    stages = spec_parser.get_stages(spec)
    if not stages:
        print("No stages in spec. Nothing to apply.", file=sys.stderr)
        return 1

    # Check file modification
    if runtime_path.exists() and target.get("last_apply"):
        import os
        file_mtime = os.path.getmtime(runtime_path)
        from datetime import datetime
        last_apply_str = target["last_apply"]
        try:
            last_apply_ts = datetime.fromisoformat(last_apply_str).timestamp()
            if file_mtime > last_apply_ts and not force:
                print(f"WARNING: {runtime_path} has been modified since last apply.")
                print(f"  Last apply: {last_apply_str}")
                print(f"  File modified: {datetime.fromtimestamp(file_mtime).isoformat()}")
                print(f"\nUse --force to overwrite, or adopt the changes first.")
                return 1
        except (ValueError, TypeError):
            pass

    generated_runtime_paths = [str(runtime_path)]

    # Generate .lobster file
    lobster_content = lobster_adapter.generate_lobster(stages, name)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(lobster_content)

    # Update registry
    from datetime import datetime, timezone
    registry.update_field(name, kind, "last_apply", datetime.now(timezone.utc).isoformat(), args.registry_path)

    print(f"Applied: pipeline/{name}")
    print(f"  Generated: {runtime_path}")

    # Check for parallel stages — generate .prose if needed
    parallel_stages = [s for s in stages if s.get("parallel")]
    if parallel_stages:
        from clawscaffold.scaffold.adapters import openprose as prose_adapter
        prose_path = runtime_path.with_suffix(".prose")
        prose_content = prose_adapter.generate_prose(parallel_stages, name)
        prose_path.write_text(prose_content)
        generated_runtime_paths.append(str(prose_path))
        print(f"  Generated: {prose_path} (parallel stages)")

    registry.update_runtime_paths(name, kind, generated_runtime_paths, args.registry_path)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scaffold", description="OpenClaw pipeline scaffolder")
    parser.add_argument("--registry", dest="registry_path", type=Path, default=registry.DEFAULT_REGISTRY_PATH)

    sub = parser.add_subparsers(dest="command")

    # adopt
    adopt_p = sub.add_parser("adopt", help="Adopt an existing pipeline")
    adopt_p.add_argument("--kind", default="pipeline")
    adopt_p.add_argument("--source", required=True)
    adopt_p.add_argument("--name", required=True)

    # audit
    audit_p = sub.add_parser("audit", help="Audit a managed pipeline")
    audit_p.add_argument("--name", required=True)

    # create
    create_p = sub.add_parser("create", help="Create a new pipeline from template")
    create_p.add_argument("--kind", default="pipeline")
    create_p.add_argument("--name", required=True)

    # apply
    apply_p = sub.add_parser("apply", help="Generate runtime files from spec")
    apply_p.add_argument("--name", required=True)
    apply_p.add_argument("--force", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "adopt":
        return cmd_adopt(args)
    elif args.command == "audit":
        return cmd_audit(args)
    elif args.command == "create":
        return cmd_create(args)
    elif args.command == "apply":
        return cmd_apply(args)
    else:
        parser.print_help()
        return 0
