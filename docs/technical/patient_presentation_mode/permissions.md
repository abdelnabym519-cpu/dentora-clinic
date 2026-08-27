# Patient Presentation Mode — permissions

- `patient_presentation_mode.read`: read the current patient presentation.

The router additionally requires `ClinicContext.role == "dentist"`. Having the permission alone is not sufficient for non-dentist roles.

Role defaults: dentist = read; admin/hygienist/assistant/receptionist = none.
