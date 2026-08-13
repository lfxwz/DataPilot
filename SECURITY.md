# Security policy

## Current security boundary

DataPilot is under active development. Do not connect this milestone to production or
sensitive databases.

The intended analytical execution boundary is:

1. A dedicated database login owns no database objects.
2. The login receives only explicitly required `CONNECT`, `USAGE`, and `SELECT` grants.
3. Every execution starts a read-only transaction with a statement timeout.
4. SQL is parsed as an AST and checked against operation, schema, table, and function policy.
5. Queries are limited by rows, time, and eventually estimated cost.
6. Returned artifacts are classified and redacted before being exposed to an LLM or trace.

AST validation is not a substitute for database authorization. A parser defect, unsupported
dialect construct, database function, view, or extension must not be able to grant write or
administrative capability.

## Generated Python boundary

Generated Python is disabled unless the operator sets `DATAPILOT_ENABLE_GENERATED_PYTHON=true`.
When enabled, admission and execution are separate controls:

1. A Python AST policy requires exactly one `analyze(data)` entrypoint and an import allowlist.
2. Dynamic execution, file I/O, network clients, subprocesses, reflection, dangerous serialization,
   dataset download helpers, and dunder access are rejected before execution.
3. The policy decision contains the SHA-256 hash of the exact admitted code; the executor verifies
   that hash again immediately before execution.
4. Code and bounded JSON records are sent over container stdin. No host directory, Docker socket,
   database URL, API key, or process environment is mounted into the container.
5. The one-shot container uses `--network none`, a read-only root, a non-root UID, all capabilities
   dropped, `no-new-privileges`, and CPU, memory, process, output-size, and wall-time limits.
6. Only a typed JSON result is accepted. Generated analysis is always marked experimental.

Static policy plus Docker isolation reduces risk but does not make arbitrary generated code safe for
sensitive multi-tenant workloads. Production deployment should replace local Docker CLI orchestration
with a separately authenticated sandbox worker pool on isolated nodes, immutable digest-pinned images,
seccomp/AppArmor policy, per-tenant queues, audit retention, and admission-rate limits. Never mount the
Docker socket into the public API container.

## Operational metadata boundary

Analysis run history uses a separate `datapilot_metadata` login. It has only `USAGE` on
`datapilot_meta` and `SELECT`, `INSERT`, and `UPDATE` on `analysis_runs`. It has no Olist schema access,
no `DELETE`, no DDL privilege, and no ownership. This separation preserves the analytics role's forced
read-only guarantee while allowing append-and-finalize audit records. Production credentials must be
injected through managed secrets and should not reuse the local Compose examples.

## Secrets

- Never commit `.env` or credentials.
- Use short-lived or managed secrets outside local development.
- Logs and traces must not contain connection URLs, API keys, cookies, or authorization headers.
- Rotate any credential that is accidentally exposed.

## Reporting vulnerabilities

Until a private reporting channel is published, do not open a public issue containing an
exploit, credential, or sensitive dataset. Contact the repository owner privately.
