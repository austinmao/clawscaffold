"""PaperclipAdapter — orchestrates detection, generation, import, and key generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .catalog_reader import read_catalog_agents
from .cli_runner import ImportResult, run_company_import
from .detection import detect_paperclip
from .gateway_register import GatewayRegistration, register_agents_with_gateway
from .hierarchy_reader import merge_agents
from .key_generator import KeyGenSummary, generate_keys
from .temp_dir_builder import build_import_directory


@dataclass
class SyncResult:
    """Result of a full sync operation."""

    agent_count: int = 0
    import_result: ImportResult | None = None
    gateway_result: GatewayRegistration | None = None
    key_summary: KeyGenSummary | None = None
    warnings: list[str] = field(default_factory=list)
    dry_run_yaml: str = ""


class PaperclipAdapter:
    """Optional adapter for syncing clawscaffold agents to Paperclip.

    Activates only when Paperclip is detected (env var or CLI).
    No Python Paperclip imports — shells out to CLI only.
    """

    def __init__(self, repo_root: Path | None = None):
        self._repo_root = repo_root or self._find_repo_root()

    @staticmethod
    def _find_repo_root() -> Path:
        """Find repo root by looking for CLAUDE.md or .git."""
        cwd = Path.cwd()
        for parent in [cwd, *cwd.parents]:
            if (parent / "CLAUDE.md").is_file() or (parent / ".git").is_dir():
                return parent
        return cwd

    def sync(
        self,
        dry_run: bool = False,
        filter_pattern: str | None = None,
        generate_keys_flag: bool = False,
        force_keys: bool = False,
        api_base: str | None = None,
        company_id: str | None = None,
    ) -> SyncResult:
        """Run the full sync pipeline.

        1. Detect Paperclip
        2. Read catalog + hierarchy
        3. Build temp import directory
        4. (dry-run: print YAML and return)
        5. Run company import
        6. (optional) Generate keys

        Returns:
            SyncResult with all operation results.
        """
        result = SyncResult()

        # Step 1: Detect
        env = detect_paperclip(self._repo_root)

        if not env.available and not dry_run:
            print("Paperclip not detected — skipping sync.")
            return result

        # Allow explicit overrides from caller
        resolved_api_url = api_base or env.api_url or "http://localhost:3101"
        resolved_company_id = company_id or env.company_id

        if not resolved_company_id and not dry_run:
            print("ERROR: No company ID found. Pass --company-id or set PAPERCLIP_COMPANY_ID.")
            return result

        # Step 2: Read catalog + merge hierarchy
        catalog_agents = read_catalog_agents(self._repo_root, filter_pattern=filter_pattern)
        if not catalog_agents:
            print(f"No agents found matching filter: {filter_pattern or '*'}")
            return result

        merged = merge_agents(catalog_agents, self._repo_root)
        result.agent_count = len(merged)

        # Step 3: Build import directory
        import_dir = build_import_directory(merged, self._repo_root)
        result.warnings.extend(import_dir.warnings)

        # Step 4: Dry run
        if dry_run:
            result.dry_run_yaml = yaml.dump(
                import_dir.paperclip_yaml, default_flow_style=False, sort_keys=False
            )
            print(result.dry_run_yaml)
            # Print warnings
            for w in result.warnings:
                print(w)
            print(f"\n{result.agent_count} agents would be synced.")
            return result

        # Step 5: Import
        print(
            f"Importing {result.agent_count} agents to Paperclip"
            f" (company: {resolved_company_id})..."
        )
        result.import_result = run_company_import(
            temp_dir=import_dir.path,
            company_id=resolved_company_id,
            api_base=resolved_api_url,
            paperclip_dir=env.paperclip_dir,
        )

        if result.import_result.errors:
            for err in result.import_result.errors:
                print(f"  ERROR: {err}")

        # Step 6: Register agents with OpenClaw gateway
        print("Registering agents with OpenClaw gateway...")
        result.gateway_result = register_agents_with_gateway(merged, self._repo_root)
        if result.gateway_result.errors:
            for err in result.gateway_result.errors:
                print(f"  GATEWAY ERROR: {err}")

        # Step 7: Key generation
        if generate_keys_flag:
            print("Generating API keys...")
            result.key_summary = generate_keys(
                merged,
                company_id=resolved_company_id,
                force=force_keys,
                paperclip_dir=env.paperclip_dir,
            )

            if result.key_summary.errors:
                for err in result.key_summary.errors:
                    print(f"  KEY ERROR: {err}")

        # Print summary
        self._print_summary(result)

        # Print warnings
        for w in result.warnings:
            print(f"  {w}")

        return result

    def sync_single(
        self,
        agent_id: str,
        generate_keys_flag: bool = False,
        api_base: str | None = None,
        company_id: str | None = None,
    ) -> SyncResult:
        """Sync a single agent to Paperclip (used by create/adopt/extend hooks).

        Args:
            agent_id: Catalog agent ID (e.g. "executive/cmo")
            generate_keys_flag: Whether to generate API key after import.
            api_base: Explicit API URL.
            company_id: Explicit company ID.

        Returns:
            SyncResult for the single agent.
        """
        # Use filter to select just this agent
        return self.sync(
            dry_run=False,
            filter_pattern=agent_id,
            generate_keys_flag=generate_keys_flag,
            api_base=api_base,
            company_id=company_id,
        )

    @staticmethod
    def _print_summary(result: SyncResult) -> None:
        parts: list[str] = [f"{result.agent_count} agents synced"]

        if result.import_result and result.import_result.failure_count:
            parts.append(f"{result.import_result.failure_count} import errors")

        if result.gateway_result:
            parts.append(
                f"{result.gateway_result.registered} gateway registered, "
                f"{result.gateway_result.skipped} skipped"
            )

        if result.key_summary:
            parts.append(f"{result.key_summary.generated} keys generated")
            parts.append(f"{result.key_summary.skipped} keys skipped")
            if result.key_summary.failed:
                parts.append(f"{result.key_summary.failed} key errors")

        print(f"\nSummary: {', '.join(parts)}")
