"""Regression tests for module migration targets.

Risk Engine stalled at ``to_install`` with the persisted error

    alembic upgrade risk_engine@head failed with exit code 255

while the other eight AI modules installed and the backend booted normally.
The wrapper message hid the real exception, which is

    Multiple head revisions are present for given argument 'risk_engine@head'

Alembic propagates branch labels *down the lineage*. ``atp_0001`` is a merge
revision (``down_revision = ("risk_0001", "acs_0001")``) and ``aitp_0001``
hangs off ``risk_0001`` directly, so both of their descendant chains inherit
the ``risk_engine`` label. Two of those descendants (``atp_0001`` and
``aisr_0001``) are global heads, which gives the ``risk_engine`` label two
heads — and Alembic refuses an ambiguous target before applying anything.

``alembic upgrade heads`` (the boot entrypoint) is not ambiguous, which is why
the schema was always correct and only the *module install* failed.

The fix targets the revision the module owns instead of the label. These tests
pin the root cause, the fix, and the two properties that make it safe:

* on an already-migrated database the module-owned target is a no-op, so no
  ``CREATE TABLE`` is re-run against a schema Dentora already owns;
* on a fresh database it still applies the module's revisions in dependency
  order, so foreign-key targets exist first.

Everything here reads the Alembic script graph and monkeypatches the
subprocess, so no database is required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.plugins import processor as processor_mod
from app.core.plugins.alembic_paths import (
    _alembic_cfg_path,
    _module_versions_dir,
    resolve_module_branch_head,
)
from app.core.plugins.loader import discover_modules
from app.core.plugins.processor import PendingProcessor, _alembic_cmd

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


@pytest.fixture(scope="module")
def script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_alembic_cfg_path())))


@pytest.fixture(scope="module")
def modules() -> dict:
    return {m.name: m for m in discover_modules()}


def _processor() -> PendingProcessor:
    # Constructing an engine/sessionmaker does not connect; _run_migrate only
    # needs the object to exist.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return PendingProcessor(async_sessionmaker(engine, expire_on_commit=False))


# --- The root cause, pinned -------------------------------------------------


def test_the_risk_engine_branch_label_is_ambiguous(script: ScriptDirectory) -> None:
    """``risk_engine@head`` cannot resolve — this is the exit-code-255 cause."""
    with pytest.raises(CommandError, match="Multiple head revisions"):
        script.get_revision("risk_engine@head")

    carriers = sorted(
        rev.revision
        for rev in script.walk_revisions()
        if "risk_engine" in (rev.branch_labels or ())
    )
    heads = set(script.get_heads())
    assert [r for r in carriers if r in heads] == ["aisr_0001", "atp_0001"], (
        "two global heads inherit the risk_engine label through atp_0001's merge "
        "edge and through aitp_0001 -> tsim_0001 -> aisr_0001"
    )


def test_risk_engine_is_the_only_ambiguous_label(script: ScriptDirectory) -> None:
    """No other module branch is affected — matching 8 installed / 1 failed."""
    labels = set()
    for rev in script.walk_revisions():
        labels.update(rev.branch_labels or ())

    ambiguous = []
    for label in sorted(labels):
        try:
            script.get_revision(f"{label}@head")
        except CommandError:
            ambiguous.append(label)
    assert ambiguous == ["risk_engine"]


# --- The fix: target the revision the module owns ---------------------------


def test_risk_engine_resolves_to_its_own_revision(script: ScriptDirectory, modules: dict) -> None:
    own = resolve_module_branch_head(modules["risk_engine"])
    assert own == "risk_0001"
    assert script.get_revision(own).revision == "risk_0001"


def test_every_branched_module_target_is_unambiguous_and_owned(
    script: ScriptDirectory, modules: dict
) -> None:
    """For every module with its own branch, the target must resolve to exactly
    one revision, and that revision must live in the module's own directory."""
    checked = 0
    for name, module in sorted(modules.items()):
        versions_dir = _module_versions_dir(module)
        if versions_dir is None:
            continue
        own = resolve_module_branch_head(module)
        assert own is not None, f"{name} has a versions dir but no resolvable head"
        rev = script.get_revision(own)  # raises if ambiguous or unknown
        assert rev.revision == own
        assert Path(rev.path).resolve().parent == versions_dir, (
            f"{name}: {rev.path} is not owned by {versions_dir}"
        )
        checked += 1
    assert checked >= 20, f"expected the real module branches, saw {checked}"


@pytest.mark.parametrize("name", AI_SCOPE)
def test_ai_scope_migration_targets(name: str, script: ScriptDirectory, modules: dict) -> None:
    """Each of the nine resolves without ambiguity (or legitimately has none)."""
    module = modules[name]
    own = resolve_module_branch_head(module)
    if own is None:
        # ai_clinical_report and clinical_copilot ship no migrations: _has_branch
        # is False and _run_migrate is skipped entirely.
        assert _module_versions_dir(module) is None
        return
    assert script.get_revision(own).revision == own


def test_labels_can_point_at_another_modules_revision(
    script: ScriptDirectory, modules: dict
) -> None:
    """Why ownership beats labels: these labels resolve outside their module."""
    assert script.get_revision("ai_treatment_planning@head").revision == "aisr_0001"
    assert script.get_revision("treatment_simulation@head").revision == "aisr_0001"
    assert resolve_module_branch_head(modules["ai_treatment_planning"]) == "aitp_0001"
    assert resolve_module_branch_head(modules["treatment_simulation"]) == "tsim_0001"
    assert resolve_module_branch_head(modules["ai_second_review"]) == "aisr_0001"


# --- Safety property 1: no-op on an already-migrated database ---------------


@pytest.mark.parametrize("current_head", ["atp_0001", "aitp_0001", "aisr_0001", "tsim_0001"])
def test_module_owned_target_is_a_noop_when_already_applied(
    script: ScriptDirectory, current_head: str
) -> None:
    """Their database is fully migrated, so risk_0001 is already applied as an
    ancestor. Upgrading to it must apply nothing — no duplicate CREATE TABLE."""
    lineage = {rev.revision for rev in script.iterate_revisions(current_head, "base")}
    assert "risk_0001" in lineage, f"{current_head} should imply risk_0001"
    assert script._upgrade_revs("risk_0001", current_head) == []


# --- Safety property 2: correct ordering on a fresh database ---------------


def test_fresh_database_applies_foreign_key_targets_first(script: ScriptDirectory) -> None:
    steps = [step.revision.revision for step in script._upgrade_revs("risk_0001", [])]
    assert steps == ["0001", "pat_0001", "risk_0001"], steps


def test_fresh_database_applies_the_whole_ai_chain_in_order(script: ScriptDirectory) -> None:
    steps = [step.revision.revision for step in script._upgrade_revs("aisr_0001", [])]
    assert steps == ["0001", "pat_0001", "risk_0001", "aitp_0001", "tsim_0001", "aisr_0001"]


# --- The invocation itself -------------------------------------------------


@pytest.mark.asyncio
async def test_run_migrate_targets_the_module_owned_revision(
    modules: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_cmd(args: list[str]) -> str | None:
        calls.append(args)
        return args[-1]

    monkeypatch.setattr(processor_mod, "_alembic_cmd", fake_cmd)
    applied = await _processor()._run_migrate(modules["risk_engine"])
    assert calls == [["upgrade", "risk_0001"]], calls
    assert applied == "risk_0001"


@pytest.mark.asyncio
async def test_run_migrate_skips_modules_without_a_branch(
    modules: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(args: list[str]) -> str | None:  # pragma: no cover - must not run
        raise AssertionError(f"alembic should not be invoked: {args}")

    monkeypatch.setattr(processor_mod, "_alembic_cmd", boom)
    for name in ("ai_clinical_report", "clinical_copilot"):
        assert await _processor()._run_migrate(modules[name]) is None


@pytest.mark.asyncio
async def test_run_migrate_falls_back_to_the_label_when_ownership_is_unknown(
    modules: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the graph cannot be loaded, keep the previous behaviour rather than
    skipping the migration silently."""
    calls: list[list[str]] = []
    monkeypatch.setattr(processor_mod, "resolve_module_branch_head", lambda _m: None)
    monkeypatch.setattr(processor_mod, "_alembic_cmd", lambda a: calls.append(a) or a[-1])
    await _processor()._run_migrate(modules["risk_engine"])
    assert calls == [["upgrade", "risk_engine@head"]]


def test_alembic_cmd_returns_the_resolved_revision_for_a_plain_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``applied_revision`` bookkeeping must survive the change of target form."""
    ran: list[list[str]] = []

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN202
        ran.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(processor_mod.subprocess, "run", fake_run)
    assert _alembic_cmd(["upgrade", "risk_0001"]) == "risk_0001"
    assert ran and ran[0][-2:] == ["upgrade", "risk_0001"]
    assert _alembic_cmd(["downgrade", "risk_0001"]) is None
