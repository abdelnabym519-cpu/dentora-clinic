"""Service-layer tests for dental_3d scene synthesis + persistence.

Covers:
- default synthesis from the odontogram ``ToothRecord`` universe
- merge semantics (odontogram drives condition/presence, persisted row
  drives view state)
- upsert semantics (one row per patient)
- clinic isolation at the service layer
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.models import Clinic
from app.modules.dental_3d.models import DentalScene as DentalSceneRow
from app.modules.dental_3d.schemas import DentalSceneUpdate, Tooth3D
from app.modules.dental_3d.service import DentalSceneService
from app.modules.odontogram.models import ToothRecord
from app.modules.patients.models import Patient


async def _record(db: AsyncSession, clinic_id, patient_id, number: int, condition: str) -> None:
    db.add(
        ToothRecord(
            id=uuid4(),
            clinic_id=clinic_id,
            patient_id=patient_id,
            tooth_number=number,
            tooth_type="deciduous" if number >= 51 else "permanent",
            general_condition=condition,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_default_scene_covers_full_permanent_dentition(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert scene.persisted is False
    assert scene.generator == "synthetic"
    assert scene.segmentation.status == "not_available"
    assert len(scene.teeth) == 32
    assert all(t.present for t in scene.teeth)
    assert all(t.condition == "healthy" for t in scene.teeth)
    assert {t.tooth_number for t in scene.teeth} == {n for n in range(11, 49) if 1 <= n % 10 <= 8}


@pytest.mark.asyncio
async def test_odontogram_records_drive_condition_and_presence(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await _record(db_session, test_patient.clinic_id, test_patient.id, 16, "caries")
    await _record(db_session, test_patient.clinic_id, test_patient.id, 46, "missing")

    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    by_number = {t.tooth_number: t for t in scene.teeth}
    assert by_number[16].condition == "caries"
    assert by_number[16].present is True
    assert by_number[46].condition == "missing"
    assert by_number[46].present is False


@pytest.mark.asyncio
async def test_deciduous_records_join_the_scene(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await _record(db_session, test_patient.clinic_id, test_patient.id, 75, "caries")

    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    numbers = [t.tooth_number for t in scene.teeth]
    assert 75 in numbers
    # 32 permanent + 1 deciduous record, in stable numeric order.
    assert len(numbers) == 33
    assert numbers == sorted(numbers)


@pytest.mark.asyncio
async def test_persisted_view_state_merges_over_recomputed_conditions(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await _record(db_session, test_patient.clinic_id, test_patient.id, 16, "caries")

    await DentalSceneService.save_for_patient(
        db_session,
        test_patient.clinic_id,
        test_patient.id,
        None,
        DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=False, color="#EF4444")]),
    )

    # The odontogram changes underneath (caries → crown).
    record = (
        await db_session.execute(select(ToothRecord).where(ToothRecord.tooth_number == 16))
    ).scalar_one()
    record.general_condition = "crown"
    await db_session.commit()

    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert scene.persisted is True
    by_number = {t.tooth_number: t for t in scene.teeth}
    # Condition/presence stay odontogram-driven...
    assert by_number[16].condition == "crown"
    # ...while view state persists.
    assert by_number[16].visible is False
    assert by_number[16].color == "#EF4444"
    # Untouched teeth fall back to defaults.
    assert by_number[11].visible is True
    assert by_number[11].color is None


@pytest.mark.asyncio
async def test_save_is_upsert_one_row_per_patient(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    await DentalSceneService.save_for_patient(
        db_session,
        test_patient.clinic_id,
        test_patient.id,
        None,
        DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=False)]),
    )
    await DentalSceneService.save_for_patient(
        db_session,
        test_patient.clinic_id,
        test_patient.id,
        None,
        DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=True)]),
    )

    rows = (
        (
            await db_session.execute(
                select(DentalSceneRow).where(DentalSceneRow.patient_id == test_patient.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1

    scene = await DentalSceneService.get_for_patient(
        db_session, test_patient.clinic_id, test_patient.id
    )
    assert {t.tooth_number: t for t in scene.teeth}[16].visible is True


@pytest.mark.asyncio
async def test_unique_patient_constraint_enforced_at_db_level(
    db_session: AsyncSession, test_patient: Patient
) -> None:
    db_session.add(
        DentalSceneRow(clinic_id=test_patient.clinic_id, patient_id=test_patient.id, teeth=[])
    )
    await db_session.flush()
    db_session.add(
        DentalSceneRow(clinic_id=test_patient.clinic_id, patient_id=test_patient.id, teeth=[])
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_wrong_clinic_sees_defaults_not_overrides(
    db_session: AsyncSession, test_patient: Patient, test_clinic: Clinic
) -> None:
    await DentalSceneService.save_for_patient(
        db_session,
        test_patient.clinic_id,
        test_patient.id,
        None,
        DentalSceneUpdate(teeth=[Tooth3D(tooth_number=16, visible=False)]),
    )

    # A different clinic asks for the same patient id.
    other_clinic = Clinic(
        id=uuid4(), name="Other Clinic", tax_id="B99999999", address={}, settings={}
    )
    db_session.add(other_clinic)
    await db_session.flush()

    scene = await DentalSceneService.get_for_patient(db_session, other_clinic.id, test_patient.id)
    assert scene.persisted is False  # no cross-clinic leak of saved state
    assert {t.tooth_number: t for t in scene.teeth}[16].visible is True
