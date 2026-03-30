"""Shell out to Paperclip CLI for import and key generation."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportResult:
    """Result of running company import."""

    success_count: int = 0
    failure_count: int = 0
    errors: list[str] = field(default_factory=list)
    raw_output: str = ""


@dataclass
class KeyResult:
    """Result of generating a single agent key."""

    key: str
    success: bool
    token: str = ""
    agent_uuid: str = ""
    company_uuid: str = ""
    error: str = ""


def run_company_import(
    temp_dir: Path,
    company_id: str,
    api_base: str,
    paperclip_dir: Path | None = None,
) -> ImportResult:
    """Run pnpm paperclipai company import.

    Args:
        temp_dir: Directory containing .paperclip.yaml + agents/
        company_id: Paperclip company UUID
        api_base: Paperclip API base URL
        paperclip_dir: services/paperclip directory (for pnpm cwd)

    Returns:
        ImportResult with counts and any errors.
    """
    cmd = [
        "pnpm",
        "paperclipai",
        "company",
        "import",
        str(temp_dir),
        "--target",
        "existing",
        "--company-id",
        company_id,
        "--collision",
        "rename",
        "--yes",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(paperclip_dir) if paperclip_dir else None,
            shell=False,
        )

        import_result = ImportResult(raw_output=result.stdout + result.stderr)

        if result.returncode == 0:
            # Count agents from output (best effort)
            lines = result.stdout.splitlines()
            for line in lines:
                if (
                    "imported" in line.lower()
                    or "created" in line.lower()
                    or "updated" in line.lower()
                ):
                    import_result.success_count += 1
                elif "error" in line.lower() or "failed" in line.lower():
                    import_result.failure_count += 1
                    import_result.errors.append(line.strip())

            # If no specific counts found, assume all succeeded
            if import_result.success_count == 0 and import_result.failure_count == 0:
                import_result.success_count = 1  # at least the import ran
        else:
            import_result.failure_count = 1
            import_result.errors.append(
                f"Import failed (exit {result.returncode}): {result.stderr.strip()}"
            )

        return import_result

    except subprocess.TimeoutExpired:
        return ImportResult(failure_count=1, errors=["Import timed out after 300s"])
    except FileNotFoundError:
        return ImportResult(
            failure_count=1, errors=["pnpm not found — is Paperclip CLI installed?"]
        )
    except OSError as exc:
        return ImportResult(failure_count=1, errors=[f"OS error running import: {exc}"])
    finally:
        # Clean up temp dir (contains auth token in .paperclip.yaml)
        shutil.rmtree(temp_dir, ignore_errors=True)


def generate_agent_key(
    agent_key: str,
    company_id: str,
    paperclip_dir: Path | None = None,
) -> KeyResult:
    """Run pnpm paperclipai agent local-cli for a single agent.

    Args:
        agent_key: Short Paperclip agent key (e.g. "cmo")
        company_id: Paperclip company UUID
        paperclip_dir: services/paperclip directory

    Returns:
        KeyResult with token and UUIDs on success.
    """
    cmd = [
        "pnpm",
        "paperclipai",
        "agent",
        "local-cli",
        agent_key,
        "--company-id",
        company_id,
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(paperclip_dir) if paperclip_dir else None,
            shell=False,
        )

        if result.returncode != 0:
            return KeyResult(
                key=agent_key,
                success=False,
                error=f"local-cli failed (exit {result.returncode}): {result.stderr.strip()}",
            )

        data = json.loads(result.stdout)
        return KeyResult(
            key=agent_key,
            success=True,
            token=data.get("token", data.get("apiKey", "")),
            agent_uuid=data.get("agentId", data.get("id", "")),
            company_uuid=data.get("companyId", company_id),
        )

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        return KeyResult(key=agent_key, success=False, error=str(exc))
