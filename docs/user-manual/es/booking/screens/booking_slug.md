---
module: booking
screen: public
route: /booking/[slug]
related_endpoints:
  - GET /api/v1/booking/public/{slug}
  - GET /api/v1/booking/public/{slug}/professionals
  - GET /api/v1/booking/public/{slug}/slots
  - POST /api/v1/booking/public/{slug}
related_permissions:
related_paths:
  - backend/app/modules/booking/frontend/pages/booking/[slug].vue
  - backend/app/modules/booking/router.py
  - backend/app/modules/booking/service.py
last_verified_commit: fa7de66
---

# Reserva de cita online

Esta es la página pública que usan los pacientes para reservar una cita sin iniciar sesión en DentalPin. La clínica comparte una URL que contiene su slug público de reservas y la página guía al paciente para elegir profesional, día y hueco disponible, introducir sus datos y confirmar la cita.

La reserva se registra directamente en Agenda como una cita con estado `scheduled`. No existe un estado intermedio de confirmación pendiente.

## Lo que ve el paciente

1. El nombre de la clínica y, cuando están configurados, sus datos de contacto.
2. Un selector de profesional y un campo para elegir la fecha de la cita.
3. Las horas disponibles para el profesional y el día seleccionados.
4. Un formulario de paciente que requiere nombre, apellidos, teléfono y fecha de nacimiento. El correo electrónico y el motivo de la visita son opcionales.
5. Una pantalla de confirmación con la clínica, el profesional y la fecha/hora reservadas cuando la cita se crea correctamente.

## Disponibilidad

Los horarios disponibles proceden de los horarios de la clínica y del profesional. La página solo muestra los huecos devueltos por la API de reservas y la disponibilidad se vuelve a comprobar cuando el paciente envía la reserva, para evitar que un hueco ocupado unos instantes antes se reserve dos veces.

Si el hueco seleccionado ya no está disponible, se pide al paciente que elija otra hora y se actualiza la lista de huecos.

## Coincidencia de pacientes

DentalPin intenta reutilizar un paciente existente cuando los datos aportados permiten una coincidencia fiable. Si la coincidencia es ambigua, el flujo de reserva prefiere crear un registro de paciente separado antes que asociar la cita a la persona equivocada.

## Acceso público y límites de uso

Esta pantalla es pública y no requiere una sesión del personal de DentalPin ni permisos internos. Los endpoints públicos de metadatos, profesionales, huecos y creación de reservas tienen límites de uso para reducir abusos.

## Resolución de problemas

- **El enlace de reserva no está disponible:** el slug puede ser incorrecto o la reserva online puede estar desactivada para la clínica.
- **No aparecen horas disponibles:** revisa los horarios de la clínica y del profesional y prueba con otro día.
- **Una hora desaparece al confirmar:** otra reserva puede haber ocupado ese hueco; selecciona otra hora disponible.
- **El formulario no se envía:** comprueba que estén completos los campos obligatorios del paciente y que haya una hora seleccionada.
