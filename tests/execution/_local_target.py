"""A tiny, fully deterministic module for exercising
`LocalPythonExecutor` against a REAL subprocess — never project source
code, never anything that trains/infers/touches a real dataset.

Test-only: this module is never referenced by any production code path
(nothing under `src/researchos` imports it), and it is only reachable
through `LocalPythonExecutor` when a test explicitly allowlists
`tests.execution` as an execution module prefix — production
configuration never does that. It takes no shell input: `argparse`
options only, each mapping to one deterministic, hardcoded behavior.

`--mode metrics`/`metrics_bad` writes `metrics.json` into the process's
own current directory (which the orchestrator always sets to the run
workspace's `output/` directory) — this is the one, well-known,
structured channel `researchos.execution.metrics` reads after the
process exits; nothing here is stdout-parsed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time


def _write_metrics(path: str, *, valid: bool) -> None:
    if valid:
        payload = {
            "schema_version": "v1",
            "metrics": [
                {"name": "accuracy", "value": 0.95, "split": "test", "aggregation": "mean"},
                {"name": "epoch", "value": 5, "split": None, "aggregation": None},
            ],
        }
    else:
        # Missing the required "schema_version" key — deliberately malformed.
        payload = {"metrics": [{"name": "accuracy", "value": 0.5}]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("success", "fail", "sleep", "echo", "metrics", "metrics_bad", "large_output", "binary_stdout"),
        default="success",
    )
    parser.add_argument("--exit-code", type=int, default=7)
    parser.add_argument("--sleep-seconds", type=float, default=5.0)
    parser.add_argument("--message", default="hello from _local_target")
    parser.add_argument("--metrics-path", default="metrics.json")
    parser.add_argument("--lines", type=int, default=50000)
    args = parser.parse_args()

    if args.mode == "success":
        print("SUCCESS_MARKER")
        return 0
    if args.mode == "fail":
        print("FAILURE_MARKER", file=sys.stderr)
        return args.exit_code
    if args.mode == "sleep":
        time.sleep(args.sleep_seconds)
        print("SHOULD_NOT_REACH_HERE_IF_TIMED_OUT")
        return 0
    if args.mode == "echo":
        print(args.message)
        return 0
    if args.mode == "metrics":
        _write_metrics(args.metrics_path, valid=True)
        print("METRICS_WRITTEN")
        return 0
    if args.mode == "metrics_bad":
        _write_metrics(args.metrics_path, valid=False)
        print("BAD_METRICS_WRITTEN")
        return 0
    if args.mode == "large_output":
        for i in range(args.lines):
            print(f"line {i:08d} " + "x" * 40)
        return 0
    if args.mode == "binary_stdout":
        sys.stdout.buffer.write(bytes(range(256)) * 4)
        sys.stdout.buffer.flush()
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
