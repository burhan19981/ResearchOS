# Contributing

ResearchOS is early-stage software. Discuss substantial architecture or schema changes in an issue before implementing them. Small, focused fixes and documentation improvements are welcome once the public repository is available.

1. Fork the repository and create a descriptive branch.
2. Follow the checkout setup in the README. Use synthetic fixtures and temporary databases.
3. Keep domain behavior in `src/researchos`; keep dashboard route handlers thin. Preserve human approval boundaries, project consistency checks, and truthful provenance.
4. Add regression coverage for changed behavior. Run the affected Python suite and the full suite when shared models or migrations change. For frontend changes run lint, typecheck, tests, and build; run the browser smoke test for changes across the API/UI boundary.
5. Open a pull request explaining the problem, resulting behavior, validation, and limitations. Do not include credentials, private research, generated environments, or unrelated changes.

Submit only material you have the right to contribute. Identify copied/adapted third-party material and its license. Unless explicitly stated otherwise, contributions submitted for inclusion are provided under the project's Apache-2.0 license, as described in section 5 of [LICENSE](LICENSE). Do not assert ownership of material you cannot license.

Be respectful and constructive; focus reviews on the work. Harassment and disclosure of another person's private information are unacceptable. Report security-sensitive issues using SECURITY.md rather than a public issue.
