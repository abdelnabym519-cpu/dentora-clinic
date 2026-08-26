# Clinical Copilot permissions

| Permission | Admin | Dentist | Hygienist | Assistant | Receptionist |
| --- | --- | --- | --- | --- | --- |
| `clinical_copilot.read` | yes | yes | yes | no | no |
| `clinical_copilot.use` | no | yes | no | no | no |

`read` exposes only clinic-scoped evidence readiness/provenance. `use` allows advisory generation after the full evidence chain passes freshness checks.

The module never grants a mutation permission. No Clinical Copilot endpoint writes canonical clinical data, accepts autonomous treatment actions, or bypasses dentist review.
