# Security and privacy

## Supported use

ResearchOS is an experimental local development platform. No stable security-support period or production hardening is promised.

The dashboard has no authentication, authorization, or reliable user identity. It can expose stored research and change approval decisions. Bind it and its frontend to loopback on a trusted single-user workstation. CORS does not provide authentication or protect every request. Do not expose the API through public hosting, port forwarding, or a shared network.

The local Python executor is not an operating-system sandbox. Allowlists and path checks restrict invocation but cannot prevent an allowed module from reading files, accessing the network, or performing other actions with the process's permissions. Only execute code you trust. Keep execution disabled until you review the module and its dependencies. Approval actor strings are application conventions, not verified identities.

## Data handling

- Keep credentials in local environment variables or an untracked `.env`. Never put them in configuration payloads, prompts, issue reports, or screenshots.
- Databases, literature caches, logs, subprocess outputs, environment snapshots, and Git provenance may contain private research, paths, identifiers, or sensitive output. Review them before sharing. Automated redaction is not comprehensive.
- Provider calls transmit the supplied content to the selected external service. Review rights, privacy requirements, and provider terms before sending research data. Literature and dataset access does not imply redistribution permission.
- Use synthetic data in tests and examples. Keep SQL echo disabled with private data.
- `.gitignore` prevents some accidental additions; it cannot remove already-tracked files or sanitize history.

## Reporting

Use the repository's GitHub **Security → Report a vulnerability** option if private vulnerability reporting is enabled. If unavailable, open a minimal public issue requesting a private contact channel, without exploit details, secrets, private data, or affected personal information. Do not post sensitive reproduction material publicly. A private reporting channel must be verified before the public launch.

## Accidental disclosure

Stop further publishing. Notify the owner, revoke or rotate exposed credentials, assess exposure, and remove affected content/history in coordination with the owner. Deleting a file in a later commit does not revoke a secret or remove it from earlier commits or copies.
