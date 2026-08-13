# ADR 0002: The analytical database is read-only by construction

- Status: accepted
- Date: 2026-08-11

## Context

Classifying SQL as low, medium, or high risk inside an LLM workflow cannot enforce database
authorization. A generated query may exploit parser gaps, functions, views, or extensions.

## Decision

The core analytics workflow will never receive a credential capable of writing to the target
database. It combines least-privilege grants, read-only transactions, timeouts, resource
budgets, AST policy, and artifact redaction.

Any future write capability must use a separate workflow, separate credential, explicit
business authorization, idempotency controls, and an immutable audit record.

## Consequences

- Human approval is not treated as a substitute for least privilege.
- Local demo roles must mirror the intended permission separation.
- Integration tests must prove writes fail at the database layer.

