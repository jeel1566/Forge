# Forge documentation map

Forge is a local-first decision and learning system for coding agents. Its documentation describes how trusted, evidence-backed decisions move from a Session Handoff to a scoped rule; Forge does not store raw chats or attempt to preserve every piece of agent context.

## Start here

- [README](../README.md) — product overview, architecture summary, safety rules, and quick install.
- [Installation](INSTALLATION.md) — install, agent setup, session lifecycle, dashboard, validations, GitHub, and optional ChatGPT connector.
- [Architecture](ARCHITECTURE.md) — components, data flow, lifecycle, runtime ownership, and failure boundaries.

## Reference

- [API and MCP contract](API-MCP-SPEC.md)
- [Data model and retention](DATA-MODEL.md)
- [Structured handoff and validation template](STRUCTURED-TEMPLATES.md)
- [Backend schema constraints](BACKEND-SCHEMA.md)
- [Technical requirements](TRD.md)

## How Forge learns

- [Learning pipeline](INGESTION-PIPELINE.md)
- [Decision, verification, and coaching](EXTRACTION-VERIFICATION-COACHING.md)
- [System design and safety invariants](SYSTEM-DESIGN.md)
- [Model and agent boundary](MODEL-RUNTIME.md)

## Operations

- [Agent lifecycle](AGENT-LIFECYCLE-DESIGN.md)
- [Agent setup reference](AGENT-SETUP.md)
- [Open-source development setup](OPEN-SOURCE-SETUP.md)
- [Releasing Forge](RELEASING.md)
- [Demo runbook](HACKATHON-RUNBOOK.md)

## Historical records

- [Implementation plan](IMPLEMENTATION-PLAN.md) records earlier delivery phases.
- [Legacy removal plan](LEGACY-REMOVAL-PLAN.md) records the migration approach that preserved old data as read-only history.
