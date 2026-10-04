"""Exercise the actual example across approval, execution and artifact storage."""
import hashlib
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from examples.reproducible_experiment import run_demo
from researchos.db import create_db_engine, repository


def test_example_requires_approval_without_running_worker(tmp_path):
    output = tmp_path / "blocked"
    summary = run_demo(output, approve=False)
    assert summary["status"] == "awaiting_approval"
    assert summary["metrics"] == {}
    assert not list(output.rglob("metrics.json"))


def test_example_repeats_metrics_and_records_real_artifact_hashes(tmp_path):
    first = run_demo(tmp_path / "first", approve=True)
    second = run_demo(tmp_path / "second", approve=True)
    assert first["status"] == second["status"] == "succeeded"
    assert first["metrics"] == second["metrics"] == {"baseline_mae": 22.5, "fitted_mae": 0.0}
    assert first["dataset_sha256"] == second["dataset_sha256"]
    engine = create_db_engine("sqlite:///" + (tmp_path / "first" / "researchos.db").as_posix())
    try:
        with sessionmaker(bind=engine)() as session:
            run = repository.get_run(session, first["run_id"])
            artifacts = repository.list_artifact_metadata(session, run.project_id, run_id=run.id)
            assert {a.logical_name for a in artifacts} >= {"metrics_report", "result_manifest"}
            for artifact in artifacts:
                assert hashlib.sha256(Path(artifact.reference).read_bytes()).hexdigest() == artifact.content_hash
    finally:
        engine.dispose()


def test_existing_output_is_preserved(tmp_path):
    marker = tmp_path / "keep.txt"
    marker.write_text("existing work", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_demo(tmp_path, approve=True)
    assert marker.read_text(encoding="utf-8") == "existing work"
    assert not (tmp_path / "researchos.db").exists()
