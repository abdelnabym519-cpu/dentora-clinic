# Risk Engine permissions

- `risk_engine.read` — read the latest/history of tenant-scoped advisory results and display the Risk Map.
- `risk_engine.generate` — materialize a new append-only result from the current CaseSnapshot.
- `risk_engine.review` — dentist-only accept/reject transition for a pending result.

Default manifest roles: admin=`read,generate`; dentist=`read,generate,review`; hygienist=`read`; assistant=`read`; receptionist=none. Backend tenant scope always comes from authenticated `ClinicContext`; caller-supplied clinic IDs are not accepted by the API.
