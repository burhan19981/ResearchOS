"""Synthetic regression experiment with real local execution and provenance.

Run from the checkout with ``python -m examples.reproducible_experiment``.
Add --approve-execution to consent to the trusted example subprocess.
Upstream planning records are seeded as approved demo records, not scientific
findings or evidence that an independent reviewer approved them.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile

from sqlalchemy.orm import sessionmaker

from researchos.db import create_db_engine, init_db, repository
from researchos.db.models import DatasetLifecycleStatus, PlanningApprovalStatus, RunStatus
from researchos.execution.approval import approve_run_execution
from researchos.execution.config import ExecutionConfig
from researchos.execution.integration import create_run_from_specification, prepare_run
from researchos.execution.local_executor import LocalPythonExecutor
from researchos.execution.orchestrator import execute_run
from researchos.specification.fingerprint import compute_configuration_hash


def fit_and_measure(dataset: Path) -> dict[str, float]:
    """Fit on train rows only, then compare with a train-mean baseline."""
    with dataset.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    train = [(float(r["x"]), float(r["y"])) for r in rows if r["split"] == "train"]
    test = [(float(r["x"]), float(r["y"])) for r in rows if r["split"] == "test"]
    x_mean = statistics.mean(x for x, _ in train)
    y_mean = statistics.mean(y for _, y in train)
    slope = sum((x-x_mean)*(y-y_mean) for x, y in train) / sum((x-x_mean)**2 for x, _ in train)
    intercept = y_mean - slope*x_mean
    return {
        "baseline_mae": statistics.mean(abs(y-y_mean) for _, y in test),
        "fitted_mae": statistics.mean(abs(y-(slope*x+intercept)) for x, y in test),
    }


def worker(dataset: Path) -> None:
    metrics = fit_and_measure(dataset)
    Path("metrics.json").write_text(json.dumps({
        "schema_version": "v1",
        "metrics": [{"name": k, "value": v, "split": "test", "aggregation": "mean"}
                    for k, v in metrics.items()],
    }, indent=2), encoding="utf-8")
    print("Computed synthetic holdout metrics from CSV:", json.dumps(metrics, sort_keys=True))


def seed_specification(factory, dataset: Path, fingerprint: str) -> tuple[int, int]:
    """Seed explicitly synthetic approved planning records, then link the run spec."""
    approved = PlanningApprovalStatus.APPROVED
    with factory.begin() as s:
        project = repository.create_project(s, title="Synthetic linear regression tutorial")
        question = repository.create_research_question(s, project_id=project.id,
            question="Can a fitted line recover the known synthetic function y=3x+2?",
            planning_status=approved)
        contribution = repository.create_contribution_candidate(s, project_id=project.id,
            title="Demonstrate experiment provenance", description="Educational example, not a novel research claim.",
            planning_status=approved)
        repository.link_contribution_candidate_question(s, project_id=project.id,
            contribution_candidate_id=contribution.id, research_question_id=question.id)
        method = repository.create_methodology_version(s, project_id=project.id,
            description="Fit a line on x=0..9; compare holdout MAE on x=10..14 with the training mean.",
            planning_status=approved, contribution_candidate_id=contribution.id,
            contribution_candidate_version=1, contribution_candidate_status_at_generation="approved")
        design = repository.create_experimental_design(s, project_id=project.id,
            proposed_method="Closed-form least squares; deterministic synthetic data; separate train/test rows.",
            planning_status=approved, methodology_plan_id=method.id,
            methodology_plan_version=1, methodology_plan_status_at_generation="approved")
        record = repository.register_dataset(s, project_id=project.id, name="Generated y=3x+2",
            version="1", path_or_uri=str(dataset))
        version = repository.create_dataset_version(s, project_id=project.id, dataset_record_id=record.id,
            source_uri=str(dataset), format="csv", sample_count=15,
            split_definition={"train": "x=0..9", "test": "x=10..14"},
            content_fingerprint=fingerprint, lifecycle_status=DatasetLifecycleStatus.APPROVED)
        experiment = repository.register_experiment(s, project_id=project.id, name="Linear fit versus mean baseline")
        configuration = {"execution": {"module": "examples.reproducible_experiment",
            "arguments": ["--worker", str(dataset)]}, "dataset_sha256": fingerprint}
        spec = repository.create_experiment_specification(s, project_id=project.id,
            experiment_id=experiment.id, experimental_design_id=design.id, dataset_version_id=version.id,
            configuration=configuration, configuration_hash=compute_configuration_hash(configuration),
            planning_status=approved)
        return project.id, spec.id


def run_demo(output: Path, *, approve: bool) -> dict:
    """Create a new output directory; never overwrite an existing experiment."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dataset = output / "synthetic.csv"
    with dataset.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["x", "y", "split"])
        writer.writerows((x, 3*x+2, "train" if x < 10 else "test") for x in range(15))
    fingerprint = hashlib.sha256(dataset.read_bytes()).hexdigest()
    url = "sqlite:///" + (output / "researchos.db").as_posix()
    init_db(url)
    engine = create_db_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    config = ExecutionConfig(allowed_module_prefixes=("examples.reproducible_experiment",),
        allowed_python_executables=(sys.executable,), allowed_execution_root=output / "runs")
    try:
        project_id, spec_id = seed_specification(factory, dataset, fingerprint)
        run = create_run_from_specification(project_id, spec_id, requested_by="user:example",
            timeout_seconds=60, config=config, session_factory=factory)
        readiness = prepare_run(run.id, actor="user:example", session_factory=factory)
        if readiness.ready:
            raise RuntimeError("Expected a new run to require execution approval")
        summary = {"synthetic": True, "dataset_sha256": fingerprint, "run_id": run.id,
            "blocked_before_approval": True, "status": "awaiting_approval", "metrics": {}}
        if approve:
            approve_run_execution(run.id, actor="user:example", session_factory=factory)
            run = execute_run(run.id, actor="user:example", engine=LocalPythonExecutor(),
                config=config, session_factory=factory,
                extra_environment={"PYTHONPATH": str(Path(__file__).resolve().parents[1])})
            if run.status != RunStatus.SUCCEEDED:
                raise RuntimeError(f"Example run did not succeed: {run.status}; inspect {output}")
            with factory() as s:
                metrics = repository.list_metrics(s, project_id, run_id=run.id)
                artifacts = repository.list_artifact_metadata(s, project_id, run_id=run.id)
                summary.update(status="succeeded", metrics={m.name: m.value for m in metrics},
                    artifact_count=len(artifacts))
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New directory for the synthetic database and run artifacts")
    parser.add_argument("--approve-execution", action="store_true", help="Approve running this trusted tutorial locally")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    output = args.output or Path(tempfile.mkdtemp(prefix="researchos_demo_")) / "experiment"
    summary = run_demo(output, approve=args.approve_execution)
    print(json.dumps(summary, indent=2))
    print(f"Local results: {output.resolve()}")
    if not args.approve_execution:
        print("No experiment subprocess was started. Use --approve-execution with a NEW output directory to run it.")


if __name__ == "__main__":
    main()
