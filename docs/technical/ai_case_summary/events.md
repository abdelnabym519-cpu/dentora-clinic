# AI Case Summary — events

- `ai_case_summary.generated`: identifiers, snapshot version/source digest, provider/model and input/output digests. No summary text is emitted.
- `ai_case_summary.reviewed`: identifiers, review status, reviewer id and output digest. No clinical text is emitted.

These events are audit/integration signals. Canonical clinical source records are never modified by an event handler in this module.
