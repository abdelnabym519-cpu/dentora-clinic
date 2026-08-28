# Case Intelligence permissions

The module exposes one permission: `case_intelligence.read`.

- `admin`: wildcard access through the existing core admin rule.
- `dentist`: read.
- `hygienist`: read.
- `assistant`: read.
- `receptionist`: no Case Intelligence permission.

The router uses the existing `ClinicContext` and `require_permission` dependencies. Every source query is also constrained by the active clinic and patient identity, so a snapshot cannot be read across clinic boundaries.

There is intentionally no client-facing write permission: snapshot materialization is performed by the server while serving the read endpoint.
