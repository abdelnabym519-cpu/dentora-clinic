"""Synthetic clinical dataset for the AI-activation demo (LOCAL DEMO ONLY).

Five clearly-marked synthetic patients with enough structured evidence to
exercise the full clinical-AI pipeline deterministically:

1. ``baseline``    — healthy adult, minimal findings.
2. ``restorative`` — caries + fillings, light medical context.
3. ``perio``       — periodontal risk evidence (smoker + closed perio with
                     BOP/plaque/suppuration sites).
4. ``implant``     — missing tooth + synthetic intraoral-scan-style geometry
                     (alignment/nerve remain external-service-gated).
5. ``complete``    ★ "Complete AI Demo Case" — enough evidence for
                     Case Intelligence → Risk Engine → AI Treatment Planning
                     → dentist acceptance → Treatment Simulation → AI Second
                     Review → AI Clinical Report → Clinical Copilot.

Every datum here is FICTIONAL and machine-generated. Names carry the
``(SYNTHETIC)`` marker and patient notes state "Synthetic demo patient".
No real PHI, no real medical claims: the values only exercise the existing
Dentora domain contracts (never new clinical concepts).

The data shapes deliberately reuse the same fan-out contract as the existing
demo patients (``medical_history`` blob → normalized patients_clinical rows).
"""

from __future__ import annotations

import math
import struct
from datetime import date
from uuid import UUID

# Fixed, convention-consistent identifiers (see PATIENT_IDS in demo_data.py).
AI_BASELINE_ID = UUID("e0eebc99-9c0b-4ef8-bb6d-6bb9bd380a60")
AI_RESTORATIVE_ID = UUID("e1eebc99-9c0b-4ef8-bb6d-6bb9bd380a61")
AI_PERIO_ID = UUID("e2eebc99-9c0b-4ef8-bb6d-6bb9bd380a62")
AI_IMPLANT_ID = UUID("e3eebc99-9c0b-4ef8-bb6d-6bb9bd380a63")
AI_COMPLETE_ID = UUID("e4eebc99-9c0b-4ef8-bb6d-6bb9bd380a64")

AI_DEMO_PATIENT_IDS = [
    AI_BASELINE_ID,
    AI_RESTORATIVE_ID,
    AI_PERIO_ID,
    AI_IMPLANT_ID,
    AI_COMPLETE_ID,
]

SYNTHETIC_MARKER = (
    "SYNTHETIC DEMO PATIENT — fictional data for local AI demonstration. "
    "Not a real person; not clinical guidance."
)

# The demo clinic's Copilot engine override (existing per-clinic settings row).
COPILOT_DEMO_SETTINGS = {"provider": "ollama", "model": "qwen3:8b"}

# FDI teeth used in the synthetic odontogram specs.
_PERMANENT_TEETH = [
    *(range(11, 19)),
    *(range(21, 29)),
    *(range(31, 39)),
    *(range(41, 49)),
]

# Perio site codes mirror the module's SiteCode enum order.
_PERIO_SITES = ("MV", "V", "DV", "ML", "L", "DL")


def build_tooth_records(specs: dict[int, dict] | None = None) -> list[dict]:
    """ToothRecord payloads for a full permanent dentition with overrides."""
    specs = specs or {}
    return [
        {
            "tooth_number": n,
            "tooth_type": "permanent",
            "general_condition": specs.get(n, {}).get("condition", "healthy"),
            "surfaces": specs.get(n, {}).get("surfaces", {}),
            "notes": specs.get(n, {}).get("notes"),
        }
        for n in _PERMANENT_TEETH
    ]


def _perio_snapshot(
    *,
    pocket_by_tooth: dict[int, int] | None = None,
    bleeding: set[int] | None = None,
    plaque: set[int] | None = None,
    suppuration: set[int] | None = None,
    mobility: dict[int, int] | None = None,
) -> dict:
    """Periodontogram payload: one closed snapshot for the whole dentition.

    ``pocket_by_tooth`` applies the probing depth to all six sites of a
    tooth; observations are booleans per tooth for all six sites.
    """
    pocket_by_tooth = pocket_by_tooth or {}
    bleeding = bleeding or set()
    plaque = plaque or set()
    suppuration = suppuration or set()
    mobility = mobility or {}
    teeth = []
    for n in _PERMANENT_TEETH:
        pd_mm = pocket_by_tooth.get(n, 2)
        teeth.append(
            {
                "tooth_number": n,
                "is_present": True,
                "is_implant": False,
                "mobility": mobility.get(n),
                "sites": [
                    {
                        "site_code": code,
                        "probing_depth_mm": pd_mm,
                        "gingival_margin_mm": 1 if pd_mm >= 4 else 0,
                        "bleeding_on_probing": n in bleeding,
                        "plaque": n in plaque,
                        "suppuration": n in suppuration,
                    }
                    for code in _PERIO_SITES
                ],
            }
        )
    return {"teeth": teeth}


def _treatment(clinical_type: str, status: str, teeth: list[int]) -> dict:
    return {"clinical_type": clinical_type, "status": status, "teeth": teeth}


AI_DEMO_CASES: list[dict] = [
    {
        "key": "baseline",
        "id": AI_BASELINE_ID,
        "first_name": "Nora",
        "last_name": "Farouk (SYNTHETIC)",
        "date_of_birth": date(1994, 3, 12),
        "phone": "+20 100 111 0001",
        "email": "demo-ai-baseline@example.com",
        "gender": "female",
        "notes": SYNTHETIC_MARKER,
        "medical_history": {
            "allergies": [
                {"name": "Latex", "type": "contact", "severity": "low",
                 "reaction": "Skin irritation", "notes": "Synthetic demo entry"}
            ],
        },
        "tooth_specs": {},
        "treatments": [_treatment("prophylaxis", "performed", [11, 21])],
        "perio": _perio_snapshot(),
    },
    {
        "key": "restorative",
        "id": AI_RESTORATIVE_ID,
        "first_name": "Omar",
        "last_name": "Sami (SYNTHETIC)",
        "date_of_birth": date(1982, 7, 30),
        "phone": "+20 100 111 0002",
        "email": "demo-ai-restorative@example.com",
        "gender": "male",
        "notes": SYNTHETIC_MARKER,
        "medical_history": {
            "allergies": [],
            "medications": [
                {"name": "Multivitamin", "dosage": "1 tablet", "frequency": "daily",
                 "start_date": date(2025, 1, 15), "notes": "Synthetic demo entry"},
            ],
        },
        "tooth_specs": {
            16: {"condition": "carious", "surfaces": {"O": "caries"}},
            26: {"condition": "carious", "surfaces": {"M": "caries", "O": "caries"}},
            36: {"condition": "restored", "surfaces": {"O": "composite"}},
        },
        "treatments": [
            _treatment("filling_composite", "performed", [36]),
            _treatment("filling_composite", "planned", [16]),
            _treatment("filling_composite", "planned", [26]),
        ],
        "perio": _perio_snapshot(pocket_by_tooth={16: 3, 26: 3}, plaque={16, 26}),
    },
    {
        "key": "perio",
        "id": AI_PERIO_ID,
        "first_name": "Layla",
        "last_name": "Adel (SYNTHETIC)",
        "date_of_birth": date(1975, 11, 2),
        "phone": "+20 100 111 0003",
        "email": "demo-ai-perio@example.com",
        "gender": "female",
        "notes": SYNTHETIC_MARKER,
        "medical_history": {
            "is_smoker": True,
            "smoking_frequency": "10 cigarettes/day",
        },
        "tooth_specs": {
            31: {"condition": "mobile", "notes": "Grade 1 mobility (synthetic)"},
        },
        "treatments": [
            _treatment("scaling", "performed", [13, 14, 15, 23, 24, 25]),
            _treatment("scaling", "planned", [33, 34, 35, 43, 44, 45]),
        ],
        "perio": _perio_snapshot(
            pocket_by_tooth={n: 5 for n in (13, 14, 15, 23, 24, 25)}
            | {n: 4 for n in (33, 34, 35, 43, 44, 45)},
            bleeding={13, 14, 15, 23, 24, 25, 33, 34},
            plaque={n for n in _PERMANENT_TEETH},
            suppuration={14, 24},
            mobility={31: 1},
        ),
    },
    {
        "key": "implant",
        "id": AI_IMPLANT_ID,
        "first_name": "Sam",
        "last_name": "Youssef (SYNTHETIC)",
        "date_of_birth": date(1968, 5, 21),
        "phone": "+20 100 111 0004",
        "email": "demo-ai-implant@example.com",
        "gender": "male",
        "notes": SYNTHETIC_MARKER,
        "medical_history": {
            "surgical_history": [
                {"procedure": "Appendectomy", "surgery_date": date(2010, 6, 1),
                 "complications": None, "notes": "Synthetic demo entry"},
            ],
        },
        "tooth_specs": {36: {"condition": "missing"}, 46: {"condition": "missing"}},
        "treatments": [_treatment("implant_consult", "performed", [36, 46])],
        "perio": _perio_snapshot(),
        "mesh": True,
    },
    {
        "key": "complete",
        "id": AI_COMPLETE_ID,
        "first_name": "Amina",
        "last_name": "Hassan (SYNTHETIC)",
        "date_of_birth": date(1961, 9, 8),
        "phone": "+20 100 111 0005",
        "email": "demo-ai-complete@example.com",
        "gender": "female",
        "notes": SYNTHETIC_MARKER + " — Complete AI Demo Case (exercises the full pipeline).",
        "medical_history": {
            "is_on_anticoagulants": True,
            "anticoagulant_medication": "Warfarin",
            "inr_value": 2.6,
            "last_inr_date": date(2026, 9, 1),
            "is_smoker": True,
            "smoking_frequency": "5 cigarettes/day",
            "bruxism": True,
            "adverse_reactions_to_anesthesia": True,
            "anesthesia_reaction_details": "Prolonged dizziness after lidocaine (synthetic demo entry)",
            "allergies": [
                {"name": "Penicillin", "type": "drug", "severity": "high",
                 "reaction": "Urticaria", "notes": "Synthetic demo entry"},
            ],
            "medications": [
                {"name": "Warfarin", "dosage": "5 mg", "frequency": "daily",
                 "start_date": date(2024, 3, 10), "notes": "Synthetic demo entry"},
                {"name": "Amlodipine", "dosage": "5 mg", "frequency": "daily",
                 "start_date": date(2023, 11, 1), "notes": "Synthetic demo entry"},
            ],
            "systemic_diseases": [
                {"name": "Hypertension", "type": "cardiovascular",
                 "diagnosis_date": date(2019, 2, 1), "is_controlled": True,
                 "is_critical": False, "notes": "Synthetic demo entry"},
            ],
            "surgical_history": [
                {"procedure": "Appendectomy", "surgery_date": date(2005, 4, 15),
                 "complications": None, "notes": "Synthetic demo entry"},
            ],
        },
        "tooth_specs": {
            16: {"condition": "carious", "surfaces": {"O": "caries", "D": "caries"}},
            26: {"condition": "carious", "surfaces": {"O": "caries"}},
            36: {"condition": "missing"},
            46: {"condition": "restored", "surfaces": {"O": "amalgam"}, "notes": "Failing amalgam (synthetic)"},
        },
        "treatments": [
            _treatment("scaling", "performed", [13, 14, 23, 24]),
            _treatment("filling_composite", "planned", [16, 26]),
            _treatment("crown", "planned", [46]),
        ],
        "perio": _perio_snapshot(
            pocket_by_tooth={n: 5 for n in (13, 14, 15, 23, 24, 25)}
            | {n: 4 for n in (12, 22, 33, 34, 43, 44)},
            bleeding={13, 14, 15, 23, 24, 25, 33, 34, 43, 44},
            plaque={n for n in _PERMANENT_TEETH},
            suppuration={14, 24},
            mobility={36: 0},
        ),
        "mesh": True,
    },
]


def build_demo_arch_stl() -> bytes:
    """Deterministic SYNTHETIC intraoral-scan-style STL (binary, valid).

    A horseshoe-shaped arch band (two concentric semicircular arcs joined
    into a closed ribbon) — abstract geometry that clearly reads as a demo
    scan and passes the module's STL content sniffing. Deterministic:
    identical bytes on every call. Never derived from a real patient.
    """
    header = b"SYNTHETIC DEMO SCAN - AI activation demo - not patient data"
    triangles: list[tuple[tuple[float, float, float], ...]] = []

    segments = 32
    outer_r, inner_r = 26.0, 18.0
    height = 4.0
    for i in range(segments):
        a0 = math.pi * i / segments
        a1 = math.pi * (i + 1) / segments
        # outer arc bottom/top, inner arc bottom/top
        o0b, o1b = (outer_r * math.cos(a0), outer_r * math.sin(a0), 0.0), (
            outer_r * math.cos(a1), outer_r * math.sin(a1), 0.0)
        o0t, o1t = (o0b[0], o0b[1], height), (o1b[0], o1b[1], height)
        i0b, i1b = (inner_r * math.cos(a0), inner_r * math.sin(a0), 0.0), (
            inner_r * math.cos(a1), inner_r * math.sin(a1), 0.0)
        i0t, i1t = (i0b[0], i0b[1], height), (i1b[0], i1b[1], height)
        # band top, band bottom, outer wall, inner wall
        triangles.extend([
            (o0t, o1t, i1t), (o0t, i1t, i0t),
            (o1b, o0b, i0b), (o0b, i1b, i0b),
            (o0b, o1b, o1t), (o0b, o1t, o0t),
            (i1b, i0b, i0t), (i1b, i0t, i1t),
        ])

    def normal(a: tuple[float, float, float], b: tuple[float, float, float],
               c: tuple[float, float, float]) -> tuple[float, float, float]:
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        m = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        return (nx / m, ny / m, nz / m)

    buf = bytearray(header.ljust(80, b" ")[:80])
    buf += struct.pack("<I", len(triangles))
    for a, b, c in triangles:
        buf += struct.pack("<12fH", *normal(a, b, c), *a, *b, *c, 0)
    return bytes(buf)


MESH_TITLE = "SYNTHETIC DEMO SCAN — AI demo, not patient data"
MESH_FILENAME = "synthetic-demo-arch.stl"
