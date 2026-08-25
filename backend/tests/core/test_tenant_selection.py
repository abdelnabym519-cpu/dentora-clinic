"""Unit tests for tenant/clinic selection domain logic (no DB)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.tenancy.ports import ClinicMembershipRecord
from app.core.tenancy.selection import (
    ClinicSelectionError,
    TenantHints,
    TenantResolutionError,
    resolve_tenant_slug,
    select_clinic,
)


def _membership(
    *,
    role: str = "dentist",
    clinic_name: str = "Clinic",
    active: bool = True,
    tenant_slug: str = "default",
) -> ClinicMembershipRecord:
    return ClinicMembershipRecord(
        clinic_id=uuid4(),
        clinic_name=clinic_name,
        tenant_id=uuid4(),
        tenant_slug=tenant_slug,
        role=role,
        is_professional=role in ("dentist", "hygienist"),
        clinic_is_active=active,
    )


class TestTenantSlugResolution:
    def test_explicit_header_wins(self) -> None:
        hints = TenantHints(header_slug="acme", host_slug="other", jwt_tenant_slug="ignored")
        assert resolve_tenant_slug(hints) == "acme"

    def test_falls_back_to_default(self) -> None:
        hints = TenantHints(default_slug="default", allow_default_fallback=True)
        assert resolve_tenant_slug(hints) == "default"

    def test_strict_mode_rejects_when_no_hint(self) -> None:
        hints = TenantHints(allow_default_fallback=False)
        with pytest.raises(TenantResolutionError):
            resolve_tenant_slug(hints)

    def test_candidates_deduped_and_ordered(self) -> None:
        hints = TenantHints(header_slug="a", host_slug="a", jwt_tenant_slug="b")
        assert hints.candidate_slugs() == ["a", "b"]


class TestClinicSelection:
    def test_selects_requested_membership(self) -> None:
        a = _membership(clinic_name="A")
        b = _membership(clinic_name="B", role="receptionist")
        selected = select_clinic([a, b], requested_clinic_id=b.clinic_id)
        assert selected.clinic_id == b.clinic_id
        assert selected.role == "receptionist"

    def test_requested_clinic_not_member_raises(self) -> None:
        a = _membership()
        with pytest.raises(ClinicSelectionError):
            select_clinic([a], requested_clinic_id=uuid4())

    def test_tenant_pin_mismatch_raises(self) -> None:
        a = _membership(tenant_slug="acme")
        with pytest.raises(ClinicSelectionError):
            select_clinic([a], requested_clinic_id=a.clinic_id, requested_tenant_id=uuid4())

    def test_default_is_deterministic_by_name(self) -> None:
        z = _membership(clinic_name="Zulu")
        a = _membership(clinic_name="Alpha")
        selected = select_clinic([z, a], requested_clinic_id=None)
        assert selected.clinic_id == a.clinic_id

    def test_inactive_clinic_cannot_be_selected(self) -> None:
        a = _membership(active=False)
        with pytest.raises(ClinicSelectionError):
            select_clinic([a], requested_clinic_id=a.clinic_id)

    def test_no_memberships_raises(self) -> None:
        with pytest.raises(ClinicSelectionError):
            select_clinic([], requested_clinic_id=None)

    def test_all_inactive_falls_back_to_error(self) -> None:
        with pytest.raises(ClinicSelectionError):
            select_clinic([_membership(active=False)], requested_clinic_id=None)
