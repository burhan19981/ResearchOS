"""Git code provenance: clean repo, dirty repo, missing/non-repo path —
deterministic, never fabricated, always uses real temporary Git
repositories (never mocks `git` itself)."""

from __future__ import annotations

import subprocess

from researchos.execution.git_provenance import collect_code_provenance


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)


def test_clean_repository_reports_available_provenance(tmp_path):
    repo = tmp_path / "clean_repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    provenance = collect_code_provenance(str(repo))
    assert provenance.available is True
    assert provenance.commit is not None and len(provenance.commit) == 40
    assert provenance.branch is not None
    assert provenance.working_tree_clean is True
    assert provenance.unavailable_reason is None


def test_dirty_repository_reports_working_tree_clean_false(tmp_path):
    repo = tmp_path / "dirty_repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "a.txt").write_text("hello")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "a.txt").write_text("modified but not committed")

    provenance = collect_code_provenance(str(repo))
    assert provenance.available is True
    assert provenance.working_tree_clean is False


def test_non_git_directory_reports_unavailable_with_reason(tmp_path):
    plain_dir = tmp_path / "not_a_repo"
    plain_dir.mkdir()

    provenance = collect_code_provenance(str(plain_dir))
    assert provenance.available is False
    assert provenance.commit is None
    assert provenance.branch is None
    assert provenance.working_tree_clean is None
    assert provenance.unavailable_reason is not None


def test_repository_with_no_commits_yet_reports_unavailable(tmp_path):
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    _init_repo(repo)  # init'd, but nothing committed yet — no HEAD

    provenance = collect_code_provenance(str(repo))
    assert provenance.available is False
    assert provenance.commit is None
    assert provenance.unavailable_reason is not None


def test_never_fabricates_a_commit_sha_for_a_nonexistent_path(tmp_path):
    missing = tmp_path / "does_not_exist_at_all"
    provenance = collect_code_provenance(str(missing))
    assert provenance.available is False
    assert provenance.commit is None
