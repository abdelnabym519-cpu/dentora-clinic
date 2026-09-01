# Dentora Voice permissions

Dentora Voice declares one module permission:

- `voice.use` — permits access to the voice control surface and its validated UI-action tool.

This permission does **not** grant access to patient, schedule, billing, reporting, CBCT, 3D, or AI data. Every domain command is executed through the existing module's ToolRegistry tool, which independently re-checks its own permission against the caller's role.

Examples:

- Opening/searching a patient additionally requires `patients.read`.
- CBCT/3D/segmentation/nerve/implant-planner display additionally requires `dental_3d.read`.
- Agenda navigation requires `agenda.appointments.read`.
- Billing navigation requires `billing.read`.
- Reports navigation requires `reports.billing.read`.

Voice does not bypass ToolRegistry permissions when resolving context or executing multi-step commands. A failed permission check terminates the current plan and later steps are not executed.
