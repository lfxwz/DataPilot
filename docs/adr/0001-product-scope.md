# ADR 0001: Product scope favors auditable analytics

- Status: accepted
- Date: 2026-08-11

## Context

A broad enterprise-agent platform would require connectors, general RAG, arbitrary code
execution, write workflows, multiple agents, and extensive infrastructure before it could
demonstrate reliable data analysis.

## Decision

DataPilot will first implement a narrow, measurable vertical slice centered on PostgreSQL
and deterministic Python analytics. LLM components may plan and interpret, but may not
perform authoritative arithmetic or bypass typed tool contracts.

General document RAG, database writes, and generic code execution remain out of scope until
the SQL and analytical evaluation suites establish a reliable baseline.

## Consequences

- The project can demonstrate depth through correctness and ablation results.
- Fewer infrastructure services are required during early milestones.
- The architecture must preserve extension points without creating placeholder agents.

