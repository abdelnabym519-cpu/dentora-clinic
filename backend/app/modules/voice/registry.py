"""Extensible deterministic command registry for Dentora Voice."""

from __future__ import annotations

from dataclasses import dataclass
from re import Pattern, compile as re_compile

from .schemas import VoiceRisk


@dataclass(frozen=True)
class VoiceCommandSpec:
    name: str
    patterns: tuple[Pattern[str], ...]
    permissions: tuple[str, ...]
    risk: VoiceRisk
    context_requirements: tuple[str, ...] = ()
    clarification_policy: str = "ask"
    target: str | None = None
    available: bool = True
    blocked_reason: str | None = None
    aliases: tuple[str, ...] = ()


def _p(*patterns: str) -> tuple[Pattern[str], ...]:
    return tuple(re_compile(pattern) for pattern in patterns)


COMMANDS: tuple[VoiceCommandSpec, ...] = (
    VoiceCommandSpec(
        "OPEN_PATIENT",
        _p(
            r"^(?:افتح|فتح)\s+(?:حاله|ملف)\s+(?P<patient_name>.+)$",
            r"^open\s+(?:patient|case)\s+(?P<patient_name>.+)$",
        ),
        ("patients.read",),
        VoiceRisk.NAVIGATION,
        target="patients.search_patients",
        aliases=("افتح حاله", "افتح ملف", "open patient", "open case"),
    ),
    VoiceCommandSpec(
        "SEARCH_PATIENT",
        _p(
            r"^(?:ابحث|دور)\s+(?:عن\s+)?(?:مريض\s+)?(?P<patient_name>.+)$",
            r"^search\s+(?:for\s+)?(?:patient\s+)?(?P<patient_name>.+)$",
        ),
        ("patients.read",),
        VoiceRisk.READ,
        target="patients.search_patients",
        aliases=("ابحث عن مريض", "دور على مريض", "search patient", "search for patient"),
    ),
    VoiceCommandSpec(
        "OPEN_CBCT",
        _p(
            r"^(?:اعرض|افتح|وريني)\s+(?:اخر\s+)?(?:ال\s*)?(?:cbct|سي\s*بي\s*سي\s*تي)(?:\s+(?:بتاع|ل|للمريض)\s+(?P<patient_name>.+))?$",
            r"^(?:open|show)\s+(?:latest\s+)?cbct(?:\s+(?:for|of)\s+(?P<patient_name>.+))?$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        target="dental_3d.get_patient_scene",
        aliases=("افتح cbct", "اعرض اخر cbct", "open cbct", "show latest cbct"),
    ),
    VoiceCommandSpec(
        "SHOW_3D",
        _p(
            r"^(?:اعرض|افتح|وريني)\s+(?:ال\s*)?(?:3d|ثري\s*دي)$",
            r"^show\s+(?:the\s+)?3d(?:\s+view)?$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        target="dental_3d.get_patient_scene",
        aliases=("اعرض 3d", "وريني 3d", "show 3d", "show the 3d view"),
    ),
    VoiceCommandSpec(
        "SHOW_TOOTH_SEGMENTATION",
        _p(
            r"^(?:اعرض|اظهر|وريني)\s+(?:تقسيم|segment(?:ation)?)\s*(?:الاسنان|teeth)?$",
            r"^show\s+(?:tooth|teeth)\s+segmentation$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        target="dental_3d.get_patient_scene",
        aliases=(
            "اعرض تقسيم الاسنان",
            "اظهر segmentation",
            "show tooth segmentation",
            "show teeth segmentation",
        ),
    ),
    VoiceCommandSpec(
        "SHOW_NERVE",
        _p(
            r"^(?:اعرض|اظهر|وريني)\s+(?:ال)?(?:عصب|nerve)$",
            r"^show\s+(?:the\s+)?nerve$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        target="dental_3d.get_patient_scene",
        aliases=("اظهر العصب", "اعرض العصب", "show nerve", "show the nerve"),
    ),
    VoiceCommandSpec(
        "OPEN_IMPLANT_PLANNER",
        _p(
            r"^(?:افتح|شغل)\s+(?:ال\s*)?(?:implant\s+planning|implant\s+planner|تخطيط\s+الزراعه)$",
            r"^open\s+(?:the\s+)?implant\s+(?:planning|planner)$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        target="dental_3d.get_patient_scene",
        aliases=(
            "شغل implant planning",
            "افتح implant planner",
            "open implant planning",
            "open the implant planner",
        ),
    ),
    VoiceCommandSpec(
        "COMPARE_SCANS",
        _p(r"^قارن\s+(?:الفحص|scan).*$", r"^compare\s+(?:the\s+)?scans?$"),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        available=False,
        blocked_reason="No scan-comparison control/route is present in the approved base repository.",
        aliases=("قارن الفحص", "compare scans", "compare the scans"),
    ),
    VoiceCommandSpec(
        "SHOW_PATHOLOGY",
        _p(
            r"^(?:اعرض|اظهر|وريني)\s+(?:ال)?(?:pathology|الامراض|الباثولوجي)$",
            r"^show\s+(?:the\s+)?pathology$",
        ),
        ("dental_3d.read",),
        VoiceRisk.NAVIGATION,
        ("patient",),
        available=False,
        blocked_reason="No pathology viewer target is present in the approved base repository.",
        aliases=("اظهر pathology", "اعرض الباثولوجي", "show pathology", "show the pathology"),
    ),
    VoiceCommandSpec(
        "GO_TO_PATIENTS",
        _p(r"^(?:روح|اذهب)\s+(?:ل)?(?:المرضى|المرضي)$", r"^go\s+to\s+patients$"),
        ("patients.read",),
        VoiceRisk.NAVIGATION,
        target="/patients",
        aliases=("روح للمرضي", "اذهب للمرضي", "go to patients"),
    ),
    VoiceCommandSpec(
        "GO_TO_AGENDA",
        _p(
            r"^(?:روح|اذهب)\s+(?:ل)?(?:الاجنده|المواعيد)$",
            r"^go\s+to\s+(?:agenda|schedule)$",
        ),
        ("agenda.appointments.read",),
        VoiceRisk.NAVIGATION,
        target="/agenda",
        aliases=("روح للاجنده", "روح للمواعيد", "go to agenda", "go to schedule"),
    ),
    VoiceCommandSpec(
        "GO_TO_BILLING",
        _p(
            r"^(?:روح|اذهب)\s+(?:ل)?(?:الفواتير|الحسابات)$",
            r"^go\s+to\s+billing$",
        ),
        ("billing.read",),
        VoiceRisk.NAVIGATION,
        target="/billing",
        aliases=("روح للفواتير", "روح للحسابات", "go to billing"),
    ),
    VoiceCommandSpec(
        "GO_TO_REPORTS",
        _p(r"^(?:روح|اذهب)\s+(?:ل)?(?:التقارير)$", r"^go\s+to\s+reports$"),
        ("reports.billing.read",),
        VoiceRisk.NAVIGATION,
        target="/reports",
        aliases=("روح للتقارير", "اذهب للتقارير", "go to reports"),
    ),
)

BY_NAME = {item.name: item for item in COMMANDS}
