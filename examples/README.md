# Examples

## Reproducible local experiment

From the repository root after installation:

```sh
python -m examples.reproducible_experiment
python -m examples.reproducible_experiment --approve-execution
```

The first command demonstrates the execution-approval gate without starting the worker. The second grants approval for this trusted example and starts a real Python subprocess. Each invocation creates a new temporary output directory and prints its location; outputs remain there for inspection. For a named directory use `--output demo-results/first` (it must not exist).

The example generates 15 synthetic rows from `y=3x+2`, fits a line using ten training rows, and computes mean absolute error on five separate test rows. Expected metrics are `baseline_mae=22.5` and `fitted_mae=0.0`. It records the dataset SHA-256, specification configuration, execution approval, actual run state, structured metrics and artifact hashes. Repeat the command to compare metrics and the input hash; run timestamps and paths will differ.

This is a workflow tutorial, not a scientific discovery or a real-data benchmark. Upstream planning records are seeded with approved statuses for setup; no literature retrieval, LLM generation, independent human review or scientific validity is claimed. The execution approval uses a local actor label, not authenticated identity. The executor is not a sandbox. No credentials, GPU, network calls or external datasets are required once ResearchOS is installed.

Outputs contain local paths and environment metadata. Keep them private; share only reviewed, redacted excerpts. See the [first-use and feedback guide](../docs/TRY_RESEARCHOS.md).

## Minimal database example

After the root editable installation, run `python examples/local_project.py`. It creates a synthetic project, reads it back, prints its title, and removes the temporary database. No API calls or credentials are needed.

For the dashboard, run `npm run e2e:api` from `apps/dashboard/frontend` and run `npm run dev -- --host 127.0.0.1` in a second terminal there. The API seeder uses temporary synthetic records, including illustrative metrics and claims; these are UI fixtures, not scientific results. Stop both servers after inspection. Abrupt process termination can leave temporary files in the operating system's temporary directory.
