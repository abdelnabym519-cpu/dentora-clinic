# Risk Engine events

Risk Engine V1 does not publish cross-module mutation commands. The append-only `risk_results` row and its dentist review fields are the authoritative audit trail, while Case Intelligence already publishes snapshot materialization events.

This avoids introducing a non-transactional clinical side effect merely for notification purposes. Future subscribers may add outbox-backed `risk_engine.result.created` / `risk_engine.result.reviewed` integration events without changing the deterministic engine contract; no such event is required to compute or display a V1 result.
