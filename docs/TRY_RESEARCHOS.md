# Try ResearchOS and give useful feedback

This is an optional evaluation of an early-stage local developer tool. You do not need an API account, private dataset, or GPU for the tutorial. Use synthetic data until you have reviewed the security limitations. This exercise does not establish scientific effectiveness.

## First session

1. Follow the [installation instructions](../README.md#install-from-a-checkout) in a fresh checkout. Record your OS, Python version and the commit (`git rev-parse HEAD`).
2. Run `python -m examples.reproducible_experiment`. It should create a synthetic experiment and report `awaiting_approval` without launching the experiment subprocess.
3. Read [the example](../examples/reproducible_experiment.py) and [security guidance](../SECURITY.md). Run `python -m examples.reproducible_experiment --approve-execution` if you consent to executing this trusted code locally.
4. Open `summary.json` at the printed results location. Expect `succeeded`, `baseline_mae: 22.5`, and `fitted_mae: 0.0`. Inspect `synthetic.csv` and the run's `metrics.json`/`result_manifest.json`. Values are computed from a known synthetic linear function; zero error here is not a real-world accuracy claim.
5. Repeat in a new output directory. Metrics and the dataset hash should match; paths, run timestamps and environment provenance can differ.
6. Consider a workflow you actually need. Describe where the present example helps or falls short. Do not upload your research data to demonstrate the problem.

## Feedback to share

Open an issue only for an actual problem or actionable suggestion. Include:

- What you were trying to do, expected behavior and observed behavior.
- OS, Python version, repository commit and the minimal command that reproduces the problem.
- Whether installation and both approval paths worked, and where instructions were unclear.
- A small synthetic reproduction, if possible.

Remove credentials, email addresses, usernames, private paths, research content and dataset records from logs before sharing. Runtime databases and manifests can contain local paths and environment details. Report sensitive security issues through the repository's private vulnerability reporting instead of public issues.

## Participation and evidence

Participation is voluntary. Stars, forks and pull requests are not required. In a class, do not condition grades or access on public engagement or account creation; private feedback is fine. A student count is not a software-user count.

The maintainer should record only feedback actually received and changes actually made. Obtain permission before quoting a participant or publishing a case study. Distinguish a one-time trial from continued use or downstream dependency. This guide makes no claim that a user study has already happened.
