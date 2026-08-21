"""Dry-run the catalog mapper against a real Gesdén DPMF export.

Usage (inside the backend container):

    python scripts/dryrun_gesden_catalog.py /app/clinica-tto.dpm

Bootstraps a throwaway clinic, seeds the Dentora catalog into it,
iterates every ``treatment_catalog_item`` row in the DPMF, runs the
new ``CatalogItemMapper.apply`` against each one, and prints a
breakdown of where each Gesdén ``Tratamientos`` row landed: linked to
which seed item, or created in which category.

All writes happen inside a single transaction that is **rolled back**
at the end so the dry-run cannot pollute the database.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.core.auth.models import Clinic, User
from app.database import async_session_maker
from app.modules.catalog.models import TreatmentCatalogItem, TreatmentCategory
from app.modules.catalog.seed import seed_catalog
from app.modules.migration_import.dpmf import open_dpmf
from app.modules.migration_import.mappers.base import MapperContext, MappingResolver
from app.modules.migration_import.mappers.catalog import CatalogItemMapper
from app.modules.migration_import.models import ImportJob


async def run(dpmf_path: Path, passphrase: str | None = None) -> None:
    async with async_session_maker() as db:
        # Throwaway clinic + admin so we don't touch seeded ones.
        clinic = Clinic(id=uuid4(), name="dryrun", tax_id=f"B{uuid4().hex[:8]}")
        admin = User(
            id=uuid4(),
            email=f"dryrun-{uuid4().hex[:8]}@test.local",
            password_hash="x",
            first_name="Dry",
            last_name="Run",
        )
        db.add_all([clinic, admin])
        await db.flush()

        # Seed the Dentora catalog (the enriched one).
        summary = await seed_catalog(db, clinic.id)
        await db.flush()
        print(f"[seed] {summary}", flush=True)

        job = ImportJob(
            clinic_id=clinic.id,
            created_by=admin.id,
            status="executing",
            original_filename=dpmf_path.name,
            file_path=str(dpmf_path),
            file_size=dpmf_path.stat().st_size,
        )
        db.add(job)
        await db.flush()

        ctx = MapperContext(
            db=db,
            clinic_id=clinic.id,
            job_id=job.id,
            resolver=MappingResolver(db=db, clinic_id=clinic.id, job_id=job.id),
            import_fiscal_compliance=False,
            created_by=admin.id,
        )
        mapper = CatalogItemMapper()

        seed_codes: dict = {}
        for item in (
            await db.execute(
                select(TreatmentCatalogItem).where(
                    TreatmentCatalogItem.clinic_id == clinic.id,
                    TreatmentCatalogItem.is_system.is_(True),
                )
            )
        ).scalars():
            seed_codes[item.id] = item.internal_code

        with open_dpmf(dpmf_path, passphrase=passphrase) as handle:
            counts = handle.entity_counts()
            total = counts.get("treatment_catalog_item", 0)
            print(f"[dpmf] treatment_catalog_item rows: {total}", flush=True)
            print("-" * 110, flush=True)
            print(
                f"{'Codigo':<10} {'DescripMed (Gesdén)':<48} {'IdTipoODG':<10} {'→':<3} {'outcome':<8} {'Dentora':<30}",
                flush=True,
            )
            print("-" * 110, flush=True)

            link_count = 0
            create_count = 0
            per_category_create: Counter[str] = Counter()
            per_category_link: Counter[str] = Counter()
            unknown_tipo: Counter[int] = Counter()

            for row in handle.entity_iter("treatment_catalog_item"):
                canonical_uuid, source_id, src_system, payload_json, raw_json, _ts = row
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    payload = {}
                try:
                    raw = json.loads(raw_json) if raw_json else {}
                except json.JSONDecodeError:
                    raw = {}

                gesden_label = (
                    raw.get("DescripMed")
                    or raw.get("DescripAgd")
                    or raw.get("DescripPac")
                    or payload.get("short_name")
                    or payload.get("description")
                    or source_id
                )
                gesden_code = raw.get("Codigo") or source_id
                tipo_odg = raw.get("IdTipoODG") or raw.get("IdTipoOdg")

                result_id = await mapper.apply(
                    ctx,
                    entity_type="treatment_catalog_item",
                    payload=payload,
                    raw=raw,
                    canonical_uuid=canonical_uuid,
                    source_id=source_id,
                    source_system=src_system or "gesden",
                )
                await db.flush()

                item = (
                    await db.execute(
                        select(TreatmentCatalogItem).where(TreatmentCatalogItem.id == result_id)
                    )
                ).scalar_one()
                category = (
                    await db.execute(
                        select(TreatmentCategory).where(TreatmentCategory.id == item.category_id)
                    )
                ).scalar_one()
                outcome = "link" if item.id in seed_codes else "create"
                if outcome == "link":
                    link_count += 1
                    per_category_link[category.key] += 1
                else:
                    create_count += 1
                    per_category_create[category.key] += 1
                    if tipo_odg is None or tipo_odg in (0, ""):
                        unknown_tipo[-1] += 1
                    else:
                        try:
                            unknown_tipo[int(tipo_odg)] += 1
                        except (ValueError, TypeError):
                            unknown_tipo[-1] += 1

                label_trunc = str(gesden_label)[:48]
                print(
                    f"{str(gesden_code)[:10]:<10} "
                    f"{label_trunc:<48} "
                    f"{str(tipo_odg or '-'):<10} "
                    f"{'→':<3} {outcome:<8} "
                    f"{item.internal_code[:30]:<30}",
                    flush=True,
                )

            print("-" * 110, flush=True)
            print(f"Total: {link_count + create_count}", flush=True)
            print(f"  Linked to seed: {link_count}", flush=True)
            print(f"  Created new:    {create_count}", flush=True)
            print("  Link by category:")
            for cat, n in sorted(per_category_link.items(), key=lambda x: -x[1]):
                print(f"    {cat:<20} {n}")
            print("  Create by category:")
            for cat, n in sorted(per_category_create.items(), key=lambda x: -x[1]):
                print(f"    {cat:<20} {n}")
            if unknown_tipo:
                print("  Created — IdTipoODG breakdown:")
                for tipo, n in sorted(unknown_tipo.items(), key=lambda x: -x[1]):
                    label = f"IdTipoODG={tipo}" if tipo != -1 else "missing"
                    print(f"    {label:<20} {n}")

        # ROLL BACK — dry-run cannot persist
        await db.rollback()
        print("[rollback] dry-run complete; no rows persisted.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: dryrun_gesden_catalog.py <dpm-path> [passphrase]")
        sys.exit(2)
    dpm = Path(sys.argv[1])
    pw = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run(dpm, pw))
