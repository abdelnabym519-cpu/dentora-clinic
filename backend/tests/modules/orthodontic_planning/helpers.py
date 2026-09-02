"""Deterministic fixtures for orthodontic planning tests.

Pure-domain builders shared by the unit and API test modules: a full
permanent chart with configurable flags, a complete measurement set,
and helpers to seed odontogram rows through the DB session fixture.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.odontogram.models import ToothRecord
from app.modules.orthodontic_planning.domain import DentitionSnapshot, ToothSnapshot

PERMANENT_TEETH = tuple(q * 10 + p for q in (1, 2, 3, 4) for p in range(1, 9))


def full_chart(
    *,
    missing: tuple[int, ...] = (),
    displaced: tuple[int, ...] = (),
    rotated: tuple[int, ...] = (),
    deciduous: tuple[int, ...] = (),
    absent: tuple[int, ...] = (),
) -> DentitionSnapshot:
    """Deterministic dentition snapshot: 32 permanent slots + optional
    deciduous extras. ``absent`` teeth are omitted from the snapshot
    entirely (as if never charted)."""
    teeth = [
        ToothSnapshot(
            tooth_number=tooth,
            dentition="permanent",
            present=tooth not in missing,
            is_displaced=tooth in displaced,
            is_rotated=tooth in rotated,
        )
        for tooth in PERMANENT_TEETH
        if tooth not in absent
    ]
    teeth.extend(
        ToothSnapshot(tooth_number=tooth, dentition="deciduous", present=True)
        for tooth in deciduous
    )
    return DentitionSnapshot(teeth=tuple(teeth))


def complete_measurements(**overrides) -> dict:
    """A fully-sufficient measurement payload (all required fields)."""
    base = {
        "skeletal_pattern": "class_i",
        "growth_stage": "adolescent",
        "overjet_mm": 4.0,
        "overbite_mm": 2.5,
        "crowding_upper_mm": 2.0,
        "crowding_lower_mm": 1.5,
        "molar_relation_left": "class_i",
        "molar_relation_right": "class_i",
        "canine_relation_left": "class_i",
        "canine_relation_right": "class_i",
        "posterior_crossbite": False,
        "objectives": ["align", "space_management"],
    }
    base.update(overrides)
    return base


async def seed_odontogram(
    db: AsyncSession,
    *,
    clinic_id: UUID,
    patient_id: UUID,
    missing: tuple[int, ...] = (),
    displaced: tuple[int, ...] = (),
    rotated: tuple[int, ...] = (),
    deciduous: tuple[int, ...] = (),
    teeth: tuple[int, ...] | None = None,
) -> None:
    """Insert ToothRecord rows mirroring a chart (async, committed)."""
    chart = (teeth if teeth is not None else PERMANENT_TEETH) + deciduous
    for tooth in chart:
        if tooth in deciduous:
            dentition, condition = "deciduous", "healthy"
        else:
            dentition = "permanent"
            condition = "missing" if tooth in missing else "healthy"
        db.add(
            ToothRecord(
                id=uuid4(),
                clinic_id=clinic_id,
                patient_id=patient_id,
                tooth_number=tooth,
                tooth_type=dentition,
                general_condition=condition,
                surfaces={},
                is_displaced=tooth in displaced,
                is_rotated=tooth in rotated,
            )
        )
    await db.commit()
