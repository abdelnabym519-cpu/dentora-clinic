"""Map ``treatment_catalog_variant`` → existing ``catalog.TreatmentCatalogItem``.

DPMF carries per-tariff variants of a treatment template
(``treatment_catalog_variant``) referencing the master template via
``treatment_uuid``. Dentora's catalog has a single offering per
treatment (no tariff axis), so we don't create new catalog rows here —
instead we resolve the variant's canonical UUID to the SAME Dentora
``TreatmentCatalogItem`` that its parent ``treatment_uuid`` already
maps to.

Effect: budget_line / applied_treatment that point at a
``treatment_variant_uuid`` get a working FK target via the resolver.
The price differences between tariffs survive as
``budget_line.unit_amount`` snapshots (which the budget_line mapper
already carries verbatim).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..models import ImportWarning
from .base import MapperContext


class CatalogVariantMapper:
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
        existing = await ctx.resolver.get("treatment_catalog_variant", canonical_uuid)
        if existing is not None:
            return existing

        treatment_uuid = payload.get("treatment_uuid")
        if not treatment_uuid:
            return None

        catalog_item_id = await ctx.resolver.get("treatment_catalog_item", str(treatment_uuid))
        if catalog_item_id is None:
            ctx.db.add(
                ImportWarning(
                    job_id=ctx.job_id,
                    entity_type="treatment_catalog_variant",
                    source_id=source_id,
                    severity="warn",
                    code="catalog_variant.parent_not_mapped",
                    message="Variante de catálogo omitida: tratamiento padre no mapeado aún.",
                )
            )
            return None

        await ctx.resolver.set(
            entity_type="treatment_catalog_variant",
            canonical_uuid=canonical_uuid,
            source_system=source_system,
            dentora_table="treatment_catalog_items",
            dentora_id=catalog_item_id,
        )
        return catalog_item_id
