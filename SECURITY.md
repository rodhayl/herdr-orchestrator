# Security and execution boundaries

This is an inactive experimental portfolio prototype, not a supported production service. No security response SLA is offered.

## Execution

Use synthetic data and the offline regression suite for inspection. Git worktrees, path allowlists and schema gates protect integration boundaries; they are not an operating-system sandbox. Generated code and configured validation commands can execute processes with the host's permissions. Review them and use independent isolation before real execution.

The control UI is loopback-only. It has no independent authentication layer intended for a public service. Do not expose it directly to the internet. Resuming a real goal may invoke providers and consume usage.

Review binaries and provider authentication independently. Historical profile certification is not current authorization or assurance that a new host is configured safely. Maintenance preflight does not collect private CLI configuration files.

## Data and disclosure

Do not commit credentials, environment files, local databases, `.agy-factory/` runtime state, raw provider transcripts or unrelated project data. Ignore patterns reduce accidental staging; they are not a secret scanner and do not remove already tracked data.

A source snapshot review does not erase or certify Git history, pull-request references, cached objects, forks or attachments. Rewriting a branch is not a GitHub data purge. Review those surfaces separately before changing repository visibility; historical pull-request references may remain accessible.

Do not report secrets in a public issue. If credentials are exposed, revoke or rotate them with the issuing service; deleting a file is insufficient.

## Licensing

No project license is specified. Public visibility alone does not grant reuse rights. Generated frontend dependencies are not committed; anyone redistributing them must review and preserve the upstream license and notice requirements. SRI verification checks integrity, not licensing compliance.
