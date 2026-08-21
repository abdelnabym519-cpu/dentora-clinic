"""Map ``payment`` → :class:`payments.Payment`.

A DPMF Payment is a historical money-received record. It points at a
patient via the DPMF's `patient_uuid` (resolved through the mapping
table) and optionally carries `method` + `amount` + `paid_at`.

The DPMF debt / debt_payment_application graph is significantly richer
than Dentora's flat Payment model — allocations land in `RawEntity`
today via the catch-all path. This MVP creates the Payment row only,
which is enough to keep the patient ledger balanced for the historical
data.
"""

from __future__ import annotations

import json as _json
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.modules.payments.models import PatientEarnedEntry

from ..models import ImportWarning
from .base import MapperContext

_METHOD_MAP: dict[str, str] = {
    "cash": "cash",
    "card": "card",
    "bank_transfer": "bank_transfer",
    "transfer": "bank_transfer",
    "direct_debit": "direct_debit",
    "insurance": "insurance",
    "mutua": "insurance",
    "other": "other",
}

# Gesdén ``DCobros.Tipo`` numeric code → Dentora payment method
# enum. Based on the dominant values in the source database (Tipo=1 is
# the by-far most common, payment is cash/in-clinic; the others map to
# typical Spanish clinic patterns). Unknown codes fall back to
# "other" so the row still imports cleanly.
_PAYMENT_KIND_MAP: dict[int, str] = {
    1: "cash",
    2: "bank_transfer",
    3: "card",
    4: "direct_debit",
    5: "insurance",
}

# In a live system 90 days would be the right window for matching a
# refund to its source payment. Migration import is different: real
# Gesdén exports often have a multi-year gap between the original
# ``PagoCli`` and the refund row that voided it (post-hoc data
# entries, lump-sum reconciliations, treatments that were paid and
# then refunded years later when the work was undone). Inside the
# importer we trade strict temporal correlation for completeness —
# refunds still attach to a same-client + same-amount Payment, the
# constraint ``Σ Refund.amount ≤ Payment.amount`` keeps over-refund
# impossible, and the operator can re-assign individual refunds in
# the UI if a recovered attachment is wrong.
_REFUND_DATE_WINDOW_DAYS: int | None = None


class PaymentMapper:
    def __init__(self) -> None:
        # Clinic.currency is a snapshot field on payments.Payment;
        # resolved once per clinic and reused for the whole job.
        self._currency_cache: dict[UUID, str] = {}
        # Refund-target lookup tables, built together by a single DPMF
        # pre-pass over ``payment`` rows on first refund hit. All keys
        # are canonical (source-space) — the destination Payment.id is
        # resolved through ``EntityMapping`` afterwards, so the
        # canonical → Payment chain works regardless of family-split.
        #
        # ``_refund_target_built`` flips True after the scan so the
        # other two dicts may legitimately stay empty.
        self._refund_target_built: bool = False
        # applied_treatment_uuid → canonical_payment_uuid (first
        # positive PagoCli against that TtosMed).
        self._refund_target_by_treatment: dict[str, str] = {}
        # (client_uuid, source_amount) → list of (paid_on,
        # canonical_payment_uuid) ordered by paid_on. Used when
        # ``IdPagoCliRelacionado`` is null and the refund's
        # applied_treatment_uuid doesn't share a positive sibling —
        # we still match on "the same client paid this exact amount
        # within the refund window".
        self._refund_target_by_client_amount: dict[tuple[str, str], list[tuple[date, str]]] = {}

    async def apply(
        self,
        ctx: MapperContext,
        *,
        entity_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
        canonical_uuid: str,
        source_id: str,
        source_system: str,
    ) -> UUID | None:
        existing = await ctx.resolver.get("payment", canonical_uuid)
        if existing is not None:
            return existing

        # DPMF payments reference a Client (payer), not a Patient. Gesdén's
        # ``PacCli`` is M:N — one client (typically the head of household)
        # routinely pays for several patients (spouse + kids + dependants).
        # ``PatientClientLinkMapper`` records every (client, patient) pair
        # in ``ctx.client_to_patients``; we resolve the FULL list here so
        # a single ``PagoCli`` can be split proportionally across every
        # linked patient rather than dumped onto the first one mapped,
        # which used to inflate that patient's apparent credit while
        # leaving the rest of the family in apparent debt.
        client_uuid_external = payload.get("client_uuid")
        all_patient_ids: list[UUID] = []
        if client_uuid_external:
            all_patient_ids = list(ctx.client_to_patients.get(str(client_uuid_external), []))
        if not all_patient_ids:
            # Legacy single-patient fallback: try the sidecar (older
            # imports), then a direct ``patient_uuid`` from the payload.
            fallback: UUID | None = None
            if client_uuid_external:
                fallback = await ctx.resolver.get("patient_for_client", str(client_uuid_external))
            if fallback is None:
                patient_uuid_external = payload.get("patient_uuid")
                if patient_uuid_external:
                    fallback = await ctx.resolver.get("patient", str(patient_uuid_external))
            if fallback is None:
                await _warn(
                    ctx,
                    source_id,
                    "payment.no_patient_for_client",
                    "Pago omitido: cliente/paciente no resoluble (sin link o link no importado).",
                )
                return None
            all_patient_ids = [fallback]

        try:
            amount = Decimal(str(payload.get("amount") or "0"))
        except (InvalidOperation, TypeError):
            await _warn(ctx, source_id, "payment.invalid_amount", "Pago omitido: importe inválido.")
            return None
        if amount == 0:
            await _warn(ctx, source_id, "payment.zero_amount", "Pago omitido: importe nulo.")
            return None
        if amount < 0:
            # Gesdén ``PagoCli`` with ``Pagado < 0`` is a refund of an
            # earlier payment (linked via ``IdPagoCliRelacionado``).
            # The destination ``Refund`` entity needs a FK to the
            # original ``Payment``, so we resolve via the canonical
            # ``related_payment_uuid``. When the source row never
            # imported (rare, e.g. orphan refund in a subset), warn
            # and drop — we don't manufacture synthetic payments to
            # offset, the user explicitly chose strict refund matching.
            return await self._apply_refund(
                ctx,
                payload=payload,
                source_id=source_id,
                source_system=source_system,
                canonical_uuid=canonical_uuid,
                amount=abs(amount),
            )

        # Canonical Payment exposes ``payment_kind`` (the source numeric
        # ``Tipo`` code) and ``payment_method_uuid`` (FK to the source
        # catalog). We only decode the numeric kind here — the catalog
        # path requires a payment_method catalog importer that doesn't
        # exist yet. Unknown kinds fall back to "other".
        method = _PAYMENT_KIND_MAP.get(payload.get("payment_kind"), "other")

        paid_at = _parse_date(
            payload.get("paid_on") or payload.get("paid_at") or payload.get("payment_date")
        )
        if paid_at is None:
            # Payment.payment_date is NOT NULL — fall back to today for
            # rows whose source date is missing/unparseable. The notes
            # field captures the migration provenance for audit.
            paid_at = date.today()

        currency = await self._currency_for_clinic(ctx)

        # Preserve original Gesdén cashier when available — falls back
        # to the migration admin when the source had no user link or
        # the referenced user wasn't imported.
        recorded_by = await ctx.resolver.resolve_actor(payload.get("user_uuid"), ctx.created_by)

        from app.modules.payments.models import Payment

        # Split across linked patients when the client covers more than
        # one. Weight by the earned ledger so a family member with more
        # work done absorbs proportionally more of the payment; if no
        # patient has any earned activity yet (paid-up-front cohort)
        # the split is even.
        shares = await self._split_amounts(ctx, amount, all_patient_ids)

        first_payment_id: UUID | None = None
        for idx, (pid, share_amount) in enumerate(shares):
            note_prefix = payload.get("notes") or f"Importado dental-bridge ({source_id})"
            if len(shares) > 1:
                note = (
                    f"{note_prefix} · reparto familiar {idx + 1}/{len(shares)} "
                    f"(cliente {client_uuid_external})"
                )
            else:
                note = note_prefix
            payment = Payment(
                clinic_id=ctx.clinic_id,
                patient_id=pid,
                amount=share_amount,
                currency=currency,
                method=method,
                payment_date=paid_at,
                notes=note,
                recorded_by=recorded_by,
            )
            ctx.db.add(payment)
            await ctx.db.flush()
            if first_payment_id is None:
                first_payment_id = payment.id

        if len(shares) > 1:
            await _warn(
                ctx,
                source_id,
                "payment.split_across_family",
                f"Pago {amount} repartido entre {len(shares)} pacientes del cliente "
                f"{client_uuid_external} (proporcional al ledger earned).",
            )

        # Resolver maps the canonical_uuid to the first split row; the
        # remaining shares stay unmapped (re-runs short-circuit at the
        # top of apply() so we don't duplicate).
        assert first_payment_id is not None
        await ctx.resolver.set(
            entity_type="payment",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="payments",
            dentora_id=first_payment_id,
        )
        return first_payment_id

    async def _resolve_refund_target(
        self, ctx: MapperContext, payload: dict[str, Any]
    ) -> UUID | None:
        """Find the destination ``Payment.id`` a refund should attach
        to. Three canonical-space signals tried in order:

        1. **Explicit chain**: Gesdén's ``IdPagoCliRelacionado``
           (``payload["related_payment_uuid"]``).
        2. **Same-treatment positive**: the first positive ``PagoCli``
           booked against the same ``applied_treatment_uuid``.
        3. **Same client + same source amount**: the most recent
           positive ``PagoCli`` from the same ``client_uuid`` whose
           source ``Pagado`` equals ``abs(refund_amount)`` and whose
           ``paid_on`` falls within ``_REFUND_DATE_WINDOW_DAYS``
           before the refund. Anchored on the canonical PagoCli
           amount, not the per-patient share, so a family-split
           original Payment still matches.

        Each level resolves through ``EntityMapping`` so the
        ``Refund → Payment → patient_id`` chain stays correct.
        Returns ``None`` when no signal yields a Payment that landed
        in Dentora; the caller emits
        ``payment.refund_unmappable``.
        """
        related = payload.get("related_payment_uuid")
        if related:
            resolved = await ctx.resolver.get("payment", str(related))
            if resolved is not None:
                return resolved
        self._ensure_refund_target_index(ctx)
        at_uuid = payload.get("applied_treatment_uuid")
        if at_uuid:
            candidate = self._refund_target_by_treatment.get(str(at_uuid))
            if candidate:
                resolved = await ctx.resolver.get("payment", candidate)
                if resolved is not None:
                    return resolved
        return await self._match_refund_by_client_amount(ctx, payload)

    async def _match_refund_by_client_amount(
        self, ctx: MapperContext, payload: dict[str, Any]
    ) -> UUID | None:
        """Pick the most recent positive ``PagoCli`` from the same
        ``client_uuid`` with the same source ``Pagado`` as the
        refund's ``abs(amount)``, within the date window.
        """
        client_uuid = payload.get("client_uuid")
        if not client_uuid:
            return None
        amount = _decimal_or_none(payload.get("amount"))
        if amount is None or amount == 0:
            return None
        candidates = self._refund_target_by_client_amount.get((str(client_uuid), str(abs(amount))))
        if not candidates:
            return None
        # Iterate from the tail because the pre-pass appends in DPMF
        # iteration order (typically ascending paid_on), so the last
        # qualifying hit is the most recent. No date filter — see the
        # ``_REFUND_DATE_WINDOW_DAYS`` comment for the rationale.
        for _paid_on, canonical in reversed(candidates):
            resolved = await ctx.resolver.get("payment", canonical)
            if resolved is not None:
                return resolved
        return None

    def _ensure_refund_target_index(self, ctx: MapperContext) -> None:
        """Single DPMF scan that populates both refund-lookup tables.

        - ``_refund_target_by_treatment`` keeps the first positive
          ``PagoCli`` per ``applied_treatment_uuid``.
        - ``_refund_target_by_client_amount`` collects every positive
          ``PagoCli`` per ``(client_uuid, source_amount_str)``,
          ordered by ``paid_on`` (ascending — appends preserve
          source-iteration order). ``_match_refund_by_client_amount``
          consumes from the tail to pick the most recent that fits
          the refund's date window.

        Both tables only consider positive payments. Idempotent
        across calls via ``_refund_target_built``. No-op when
        ``ctx.handle`` is unavailable (test paths).
        """
        if self._refund_target_built:
            return
        self._refund_target_built = True
        if ctx.handle is None:
            return
        for row in ctx.handle.entity_iter("payment"):
            canonical_payment_uuid, _src_id, _src_sys, payload_json, _raw, _ts = row
            try:
                payload = _json.loads(payload_json)
            except _json.JSONDecodeError:
                continue
            try:
                amt = Decimal(str(payload.get("amount") or "0"))
            except (InvalidOperation, TypeError):
                continue
            if amt <= 0:
                continue
            at_uuid = payload.get("applied_treatment_uuid")
            if at_uuid:
                self._refund_target_by_treatment.setdefault(str(at_uuid), canonical_payment_uuid)
            client_uuid = payload.get("client_uuid")
            if client_uuid:
                paid_on = (
                    _parse_date(
                        payload.get("paid_on")
                        or payload.get("paid_at")
                        or payload.get("payment_date")
                    )
                    or date.min
                )
                key = (str(client_uuid), str(amt))
                self._refund_target_by_client_amount.setdefault(key, []).append(
                    (paid_on, canonical_payment_uuid)
                )

    async def _apply_refund(
        self,
        ctx: MapperContext,
        *,
        payload: dict[str, Any],
        source_id: str,
        source_system: str,
        canonical_uuid: str,
        amount: Decimal,
    ) -> UUID | None:
        """Import a negative ``PagoCli`` as a ``Refund`` row tied to a
        Dentora ``Payment``. Target resolution lives in
        :meth:`_resolve_refund_target` — direct ``IdPagoCliRelacionado``
        chain first, ``applied_treatment_uuid`` fallback second.

        Refund model: ``payments.Refund(payment_id, amount, method,
        reason_code, reason_note, refunded_at, refunded_by)``. The
        amount is always positive; we pass ``abs(Pagado)``.
        """
        from app.modules.payments.models import Refund

        original_payment_id = await self._resolve_refund_target(ctx, payload)
        if original_payment_id is None:
            await _warn(
                ctx,
                source_id,
                "payment.refund_unmappable",
                "Refund omitido: sin PagoCli original vinculado y sin "
                "Payment al mismo tratamiento para asociar.",
            )
            return None

        method = _PAYMENT_KIND_MAP.get(payload.get("payment_kind"), "other")
        refunded_at = _parse_date(
            payload.get("paid_on") or payload.get("paid_at") or payload.get("payment_date")
        )
        if refunded_at is None:
            refunded_at = date.today()
        refunded_at_dt = datetime(refunded_at.year, refunded_at.month, refunded_at.day, tzinfo=UTC)
        refunded_by = await ctx.resolver.resolve_actor(payload.get("user_uuid"), ctx.created_by)

        notes = payload.get("notes") or f"Importado dental-bridge (PagoCli={source_id})"
        refund = Refund(
            clinic_id=ctx.clinic_id,
            payment_id=original_payment_id,
            amount=amount,
            method=method,
            reason_code="other",
            reason_note=notes[:1000],
            refunded_at=refunded_at_dt,
            refunded_by=refunded_by,
        )
        ctx.db.add(refund)
        await ctx.db.flush()

        # Register against ``payment`` so a re-execute short-circuits
        # at the top of apply(). We don't introduce a separate
        # ``refund`` entity_type — the canonical row is a PagoCli, so
        # the natural key stays in the payment namespace.
        await ctx.resolver.set(
            entity_type="payment",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="refunds",
            dentora_id=refund.id,
        )
        return refund.id

    async def _split_amounts(
        self,
        ctx: MapperContext,
        total: Decimal,
        patient_ids: list[UUID],
    ) -> list[tuple[UUID, Decimal]]:
        """Distribute ``total`` across ``patient_ids`` weighted by each
        patient's existing ``PatientEarnedEntry`` sum, falling back to
        an even split when nobody has any earned activity yet.

        Rounding goes to two decimals; the last share absorbs any
        remainder so the splits sum exactly to ``total``.
        """
        n = len(patient_ids)
        if n == 1:
            return [(patient_ids[0], total)]
        # Pull earned-per-patient in one round-trip.
        rows = await ctx.db.execute(
            select(
                PatientEarnedEntry.patient_id,
                func.coalesce(func.sum(PatientEarnedEntry.amount), Decimal("0")),
            )
            .where(PatientEarnedEntry.patient_id.in_(patient_ids))
            .group_by(PatientEarnedEntry.patient_id)
        )
        earned_map: dict[UUID, Decimal] = {pid: Decimal("0") for pid in patient_ids}
        for pid, earned in rows.all():
            earned_map[pid] = earned or Decimal("0")
        weight_total = sum(earned_map.values())
        shares: list[tuple[UUID, Decimal]] = []
        if weight_total <= 0:
            # Even split.
            per = (total / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            allocated = Decimal("0")
            for idx, pid in enumerate(patient_ids):
                if idx == n - 1:
                    share = total - allocated
                else:
                    share = per
                    allocated += per
                shares.append((pid, share))
        else:
            allocated = Decimal("0")
            for idx, pid in enumerate(patient_ids):
                if idx == n - 1:
                    share = total - allocated
                else:
                    share = (total * earned_map[pid] / weight_total).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                    allocated += share
                shares.append((pid, share))
        return shares

    async def _currency_for_clinic(self, ctx: MapperContext) -> str:
        if ctx.clinic_id in self._currency_cache:
            return self._currency_cache[ctx.clinic_id]
        from app.core.auth.models import Clinic

        result = await ctx.db.execute(select(Clinic.currency).where(Clinic.id == ctx.clinic_id))
        currency = result.scalar_one_or_none() or "EUR"
        self._currency_cache[ctx.clinic_id] = currency
        return currency


async def _warn(ctx: MapperContext, source_id: str, code: str, message: str) -> None:
    ctx.db.add(
        ImportWarning(
            job_id=ctx.job_id,
            entity_type="payment",
            source_id=source_id,
            severity="warn",
            code=code,
            message=message,
        )
    )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
