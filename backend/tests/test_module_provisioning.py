"""Provisioning regressions: activation must reach an existing database.

Two failure modes made the AI Activation layers invisible to the frontend
even though every file and every manifest was correct on disk:

1. ``reconcile_with_db`` refreshed the ``auto_install`` *column* of an
   existing row but never re-evaluated its *state*. A database created
   before the activation holds the nine AI modules as ``uninstalled``, so
   flipping their manifests to ``auto_install=True`` changed nothing: no
   router mount, no ``modules.json`` entry, no Nuxt layer, no UI. Only a
   fresh database — or an administrator clicking Install nine times —
   ever activated them.

2. Nothing reported a manifest that promises a frontend layer whose
   directory is absent. ``resolve_layer_path`` logged a warning and
   skipped, ``modules.json`` shipped without the layer, and the symptom
   surfaced far away as ``NUXT_B6005 Could not resolve`` (or as a module
   with no UI at all).

The pure rules are tested without a database; the reconcile behaviour is
tested against the real registry with ``db_session``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugins.db_models import ModuleOperationLog, ModuleRecord
from app.core.plugins.frontend_layers import collect_layers, missing_layer_dirs
from app.core.plugins.loader import discover_modules
from app.core.plugins.service import ModuleService, should_auto_promote
from app.core.plugins.state import ModuleState

# The nine modules of the approved AI Activation scope. Risk Engine ships its
# UI inside the dental_3d layer, so it declares no layer of its own.
AI_SCOPE = [
    "case_intelligence",
    "risk_engine",
    "dental_3d",
    "ai_case_summary",
    "ai_treatment_planning",
    "ai_second_review",
    "ai_clinical_report",
    "clinical_copilot",
    "treatment_simulation",
]
LAYERED_AI = [m for m in AI_SCOPE if m != "risk_engine"]


# --- The promotion rule, without a database ---------------------------------


@pytest.mark.parametrize(
    ("state", "auto_install", "explicitly_uninstalled", "expected"),
    [
        # The activation case: shipped uninstalled, manifest now says auto.
        (ModuleState.UNINSTALLED.value, True, False, True),
        # Manifest still manual → an administrator must install it.
        (ModuleState.UNINSTALLED.value, False, False, False),
        # Somebody uninstalled it on purpose → never resurrect it.
        (ModuleState.UNINSTALLED.value, True, True, False),
        # Every other state is somebody else's decision.
        (ModuleState.INSTALLED.value, True, False, False),
        (ModuleState.TO_INSTALL.value, True, False, False),
        (ModuleState.TO_UPGRADE.value, True, False, False),
        (ModuleState.TO_REMOVE.value, True, False, False),
        (ModuleState.DISABLED.value, True, False, False),
        (ModuleState.DISABLED.value, True, True, False),
    ],
)
def test_should_auto_promote_truth_table(
    state: str, auto_install: bool, explicitly_uninstalled: bool, expected: bool
) -> None:
    assert (
        should_auto_promote(
            state=state,
            auto_install=auto_install,
            explicitly_uninstalled=explicitly_uninstalled,
        )
        is expected
    )


# --- Layer drift detection, without a database ------------------------------


def test_no_shipped_module_declares_a_layer_that_is_missing() -> None:
    """Every manifest that promises a Nuxt layer has the directory on disk.

    This is the invariant whose breach produced the NUXT_B6005 warnings: a
    layer path in ``modules.json`` (or in a manifest) with no files behind
    it. It covers all 34 layer-declaring modules, the seven AI ones
    included.
    """
    assert missing_layer_dirs(discover_modules()) == []


def test_the_ai_scope_declares_its_layers_and_auto_install() -> None:
    manifests = {m.name: m.get_manifest() for m in discover_modules()}
    for name in AI_SCOPE:
        assert name in manifests, f"{name} was not discovered"
        manifest = manifests[name]
        assert manifest.auto_install is True, f"{name} must ship installed"
        if name in LAYERED_AI:
            assert manifest.frontend is not None, f"{name} must declare a frontend block"
            assert manifest.frontend.get("layer_path") == "frontend"
        else:
            # risk_engine's UI is RiskEngineCard inside the dental_3d layer.
            assert not (manifest.frontend or {}).get("layer_path")


def test_collect_layers_emits_the_eight_expected_ai_paths() -> None:
    """The generated artifact must contain the AI layers, translated for the
    frontend container's ``/module_layers`` mount."""
    modules = {m.name: m for m in discover_modules()}
    entries = collect_layers([modules[name] for name in AI_SCOPE if name in modules])
    by_name = {e.module_name: e.path for e in entries}

    assert set(by_name) == set(LAYERED_AI)  # dental_3d is in LAYERED_AI
    assert "risk_engine" not in by_name
    for name in LAYERED_AI:
        assert by_name[name].endswith(f"{name}/frontend"), by_name[name]


# --- Reconcile behaviour, against a real database ---------------------------


async def _record(db: AsyncSession, name: str) -> ModuleRecord | None:
    result = await db.execute(select(ModuleRecord).where(ModuleRecord.name == name))
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_reconcile_promotes_a_never_installed_auto_module(
    db_session: AsyncSession,
) -> None:
    """A pre-activation row must be scheduled for install, not left behind."""
    svc = ModuleService(db_session)
    await svc.reconcile_with_db()

    # Simulate a database created before the activation: the row exists and
    # still carries the old install policy.
    record = await _record(db_session, "case_intelligence")
    assert record is not None
    record.state = ModuleState.UNINSTALLED.value
    record.auto_install = False
    record.installed_at = None
    await db_session.commit()

    await svc.reconcile_with_db()

    record = await _record(db_session, "case_intelligence")
    assert record is not None
    assert record.auto_install is True, "the manifest value must be refreshed"
    assert record.state == ModuleState.TO_INSTALL.value, (
        "reconcile must schedule the install so the pending processor runs the "
        "normal migrate -> seed -> lifecycle -> finalize pipeline"
    )


@pytest.mark.asyncio
async def test_reconcile_never_resurrects_an_explicit_uninstall(
    db_session: AsyncSession,
) -> None:
    svc = ModuleService(db_session)
    await svc.reconcile_with_db()

    record = await _record(db_session, "case_intelligence")
    assert record is not None
    record.state = ModuleState.UNINSTALLED.value
    record.installed_at = None
    db_session.add(
        ModuleOperationLog(
            module_name="case_intelligence",
            operation="uninstall",
            step="finalize",
            status="completed",
        )
    )
    await db_session.commit()

    await svc.reconcile_with_db()

    record = await _record(db_session, "case_intelligence")
    assert record is not None
    assert record.state == ModuleState.UNINSTALLED.value, (
        "an administrator's uninstall outranks the manifest default"
    )


@pytest.mark.asyncio
async def test_reconcile_leaves_disabled_and_pending_states_alone(
    db_session: AsyncSession,
) -> None:
    svc = ModuleService(db_session)
    await svc.reconcile_with_db()

    record = await _record(db_session, "ai_case_summary")
    assert record is not None
    record.state = ModuleState.DISABLED.value
    await db_session.commit()

    await svc.reconcile_with_db()

    record = await _record(db_session, "ai_case_summary")
    assert record is not None
    assert record.state == ModuleState.DISABLED.value


@pytest.mark.asyncio
async def test_reconcile_on_a_fresh_database_installs_the_ai_scope(
    db_session: AsyncSession,
) -> None:
    """The pre-existing behaviour for new rows is unchanged: straight to
    ``installed``, with nothing left pending."""
    svc = ModuleService(db_session)
    await svc.reconcile_with_db()

    for name in AI_SCOPE:
        record = await _record(db_session, name)
        assert record is not None, f"{name} has no row"
        assert record.state == ModuleState.INSTALLED.value, f"{name}: {record.state}"
        assert record.auto_install is True

    status = await svc.status()
    assert status["pending"] == []


@pytest.mark.asyncio
async def test_doctor_reports_a_manifest_layer_that_is_not_on_disk(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor must name the module instead of leaving a log line behind."""
    svc = ModuleService(db_session)
    await svc.reconcile_with_db()

    clean = await svc.doctor()
    assert clean.missing_layer_dirs == []
    assert clean.ok is True

    import app.core.plugins.service as service_mod

    monkeypatch.setattr(service_mod, "missing_layer_dirs", lambda _modules: ["case_intelligence"])
    drifted = await svc.doctor()
    assert drifted.missing_layer_dirs == ["case_intelligence"]
    assert drifted.ok is False
    assert drifted.to_dict()["missing_layer_dirs"] == ["case_intelligence"]
