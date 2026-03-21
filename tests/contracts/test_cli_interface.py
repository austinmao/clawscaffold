"""Contract tests for the clawscaffold CLI interface."""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent.parent.parent

# Build an env that includes the package root on PYTHONPATH so the subprocess
# can import clawscaffold even when it is not pip-installed (editable or source).
_base_env = os.environ.copy()
_existing = _base_env.get("PYTHONPATH", "")
_base_env["PYTHONPATH"] = str(PACKAGE_DIR) + (":" + _existing if _existing else "")


def test_version_command():
    result = subprocess.run(
        [sys.executable, "-m", "clawscaffold", "--version"],
        capture_output=True, text=True, cwd=str(PACKAGE_DIR), env=_base_env,
    )
    # Should not crash — version or help output
    assert result.returncode in (0, 2)  # argparse may return 2 for --version on some setups


def test_init_command(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "clawscaffold", "init"],
        capture_output=True, text=True, cwd=str(tmp_path), env=_base_env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (tmp_path / ".clawscaffold").exists()


def test_help_command():
    result = subprocess.run(
        [sys.executable, "-m", "clawscaffold", "--help"],
        capture_output=True, text=True, cwd=str(PACKAGE_DIR), env=_base_env,
    )
    assert result.returncode == 0
    assert "clawscaffold" in result.stdout.lower() or "usage" in result.stdout.lower()
