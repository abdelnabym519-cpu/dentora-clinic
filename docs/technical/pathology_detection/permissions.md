# Pathology Detection — permissions

The module declares two namespaced permissions via
`get_permissions()`:

- `pathology_detection.read` — view capabilities, analysis history,
  analysis detail (including findings).
- `pathology_detection.write` — run a new analysis and delete analyses.

Manifest `role_permissions`:

| Role | `pathology_detection.read` | `pathology_detection.write` |
|------|----------------------------|-----------------------------|
| admin | ✔ (`*`) | ✔ (`*`) |
| dentist | ✔ | ✔ |
| hygienist | ✔ | — |
| assistant | ✔ | — |
| receptionist | — | — |

Note: the *media* permissions (`media.documents.read`) are enforced by
the media module and are required to fetch documents for analysis. The
pathology module itself never touches storage directly beyond reading
the bytes through the media storage backend at analysis time.
