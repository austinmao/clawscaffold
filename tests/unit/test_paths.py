from __future__ import annotations

from clawscaffold.paths import repo_root


def test_repo_root_accepts_legacy_scaffold_repo_root(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAWSCAFFOLD_ROOT", raising=False)
    monkeypatch.setenv("SCAFFOLD_REPO_ROOT", str(tmp_path))

    assert repo_root() == tmp_path.resolve()


def test_repo_root_prefers_clawscaffold_root_over_legacy_override(monkeypatch, tmp_path):
    legacy_root = tmp_path / "legacy"
    preferred_root = tmp_path / "preferred"
    legacy_root.mkdir()
    preferred_root.mkdir()

    monkeypatch.setenv("SCAFFOLD_REPO_ROOT", str(legacy_root))
    monkeypatch.setenv("CLAWSCAFFOLD_ROOT", str(preferred_root))

    assert repo_root() == preferred_root.resolve()
