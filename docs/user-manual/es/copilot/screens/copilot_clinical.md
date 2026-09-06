---
module: copilot
screen: clinical
route: /copilot/clinical
related_endpoints:
  - GET /api/v1/copilot/metrics
  - GET /api/v1/copilot/nudges
  - GET /api/v1/copilot/pending
  - GET /api/v1/copilot/sessions
  - GET /api/v1/copilot/sessions/{conversation_id}/messages
  - GET /api/v1/copilot/settings
  - PATCH /api/v1/copilot/settings
  - POST /api/v1/copilot/clinical/case-intelligence
  - POST /api/v1/copilot/clinical/case-summary
  - POST /api/v1/copilot/clinical/report
  - POST /api/v1/copilot/clinical/second-review
  - POST /api/v1/copilot/clinical/treatment-suggestions
  - POST /api/v1/copilot/nudges/{nudge_id}/dismiss
  - POST /api/v1/copilot/sessions
  - POST /api/v1/copilot/sessions/{conversation_id}/confirmations/{call_id}
  - POST /api/v1/copilot/sessions/{conversation_id}/end
  - POST /api/v1/copilot/sessions/{conversation_id}/messages
related_permissions:
  - copilot.chat
  - copilot.history.read
  - copilot.history.read_all
  - copilot.supervise
  - copilot.configure
related_paths:
  - backend/app/modules/copilot/frontend/pages/copilot/clinical.vue
last_verified_commit: 466a6d1a
---

# /copilot/clinical

> _Esqueleto generado automáticamente — reemplazar con documentación real cuando se toque este módulo._

_Pantalla `/copilot/clinical` del módulo `copilot`._

## Permisos

- `copilot.chat`
- `copilot.history.read`
- `copilot.history.read_all`
- `copilot.supervise`
- `copilot.configure`

## Para qué sirve

_Pendiente de documentar._

