---
module: prescriptions
screen: prescriptions
route: /prescriptions
related_endpoints:
  - POST /api/v1/prescriptions
  - GET /api/v1/prescriptions
  - GET /api/v1/prescriptions/{prescription_id}
  - PATCH /api/v1/prescriptions/{prescription_id}
  - POST /api/v1/prescriptions/{prescription_id}/issue
  - POST /api/v1/prescriptions/{prescription_id}/cancel
  - POST /api/v1/prescriptions/{prescription_id}/void
  - GET /api/v1/prescriptions/{prescription_id}/audit
related_permissions:
  - prescriptions.read
  - prescriptions.write
  - prescriptions.issue
  - prescriptions.cancel
  - prescriptions.void
  - prescriptions.audit
related_paths:
  - backend/app/modules/prescriptions/frontend/pages/prescriptions/index.vue
  - backend/app/modules/prescriptions/router.py
last_verified_commit: e01a74e
---

# Recetas electrónicas

La pantalla **Recetas electrónicas** permite a los usuarios clínicos autorizados crear, emitir, revisar, cancelar y anular recetas dentro de la clínica seleccionada. Los registros están aislados por tenant y clínica; el backend aplica las reglas del ciclo de vida aunque un control de la interfaz se manipule.

## Crear un borrador

> Requiere `prescriptions.write`.

1. Abre **Prescriptions / Recetas** desde la navegación principal.
2. Busca al paciente y selecciona el resultado correcto de la clínica activa.
3. Introduce al menos un medicamento con nombre, dosis, frecuencia, duración, vía y cantidad. La concentración, unidad de cantidad e instrucciones son opcionales cuando corresponda.
4. Usa **Add medication** para añadir más medicamentos.
5. Pulsa **Create draft**.

El borrador puede editarse por el dentista prescriptor hasta que se emita o se cancele.

## Emitir una receta

> Requiere `prescriptions.issue` y ser el dentista prescriptor.

Pulsa **Issue** en un borrador válido. La receta pasa a `issued` y su paciente y contenido farmacológico quedan inmutables. La pantalla conserva la receta emitida como registro clínico y elimina los controles exclusivos del borrador.

## Cancelar o anular

- **Cancel** se aplica a un borrador, requiere `prescriptions.cancel` y exige un motivo.
- **Void** se aplica a una receta emitida, requiere `prescriptions.void` y exige un motivo.

Ambos estados son terminales y se conservan para auditoría. El módulo no ofrece una acción de borrado.

## Permisos

| Acción | Permiso |
|--------|---------|
| Ver lista/detalle de recetas | `prescriptions.read` |
| Crear/editar borradores | `prescriptions.write` |
| Emitir un borrador | `prescriptions.issue` |
| Cancelar un borrador | `prescriptions.cancel` |
| Anular una receta emitida | `prescriptions.void` |
| Consultar auditoría del ciclo de vida | `prescriptions.audit` |

Por defecto, los dentistas reciben todo el ciclo clínico; higienistas y asistentes tienen solo lectura, y recepción no recibe acceso a recetas.

## Resolución de problemas

- **El paciente no aparece en la búsqueda:** comprueba que pertenece a la clínica seleccionada y que tienes acceso a esa clínica.
- **Create draft está deshabilitado:** selecciona primero un paciente y completa datos válidos de medicación.
- **Issue/Cancel/Void no aparece:** la transición puede no ser válida para el estado actual, puede faltar el permiso correspondiente o puede que no seas el dentista prescriptor.
- **No se puede editar una receta terminal:** es intencionado. Las recetas emitidas, canceladas y anuladas son inmutables.
