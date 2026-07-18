# Contributing

Keep changes small and local-first. Preserve evidence immutability, use forward-only SQLite migrations, and never add transcript capture, secrets to telemetry, automatic merges, or cloud dependencies without an explicit product decision.

When changing the new rule loop, update the target/implementation status in the docs and add focused tests for idempotency, policy gates, rollback, and offline behavior. Run the Python tests, frontend build, and `git diff --check` before proposing a change.
