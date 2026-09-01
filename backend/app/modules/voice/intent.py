"""Local deterministic intent recognition for Dentora Voice."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .normalization import normalize_text
from .registry import COMMANDS, VoiceCommandSpec
from .schemas import VoiceCommandPlan, VoiceUIContext

_HIGH = 0.85
_MEDIUM = 0.60
_FUZZY_AMBIGUITY_MARGIN = 0.06

_RAW_STEP_SPLIT = re.compile(
    r"\s+(?:ثم|وبعدين|بعدها|then|and then)\s+|"
    r"\s+و(?=(?:اعرض|أظهر|اظهر|افتح|شغل|قارن)\b)|"
    r"\s+and\s+(?=(?:show|open|compare|go)\b)",
    re.IGNORECASE,
)


def split_steps(text: str) -> list[str]:
    """Split a multi-step command while preserving raw entity spelling."""
    return [part.strip() for part in _RAW_STEP_SPLIT.split(text.strip()) if part.strip()]


def _pattern_match(spec: VoiceCommandSpec, step: str):
    for pattern in spec.patterns:
        match = pattern.fullmatch(step)
        if match:
            return match, 0.98
    return None, 0.0


def _fuzzy_score(spec: VoiceCommandSpec, step: str) -> float:
    """Score against human aliases, never against regex source code."""
    aliases = spec.aliases
    if not aliases:
        return 0.0
    best = max(SequenceMatcher(None, step, normalize_text(alias)).ratio() for alias in aliases)
    # Keep fuzzy matches below exact-pattern confidence while allowing one
    # obvious recognition typo to remain usable.
    return round(best * 0.90, 3)


def _raw_patient_name(command: str, raw_step: str) -> str | None:
    """Recover patient entity from raw text so DB search keeps original spelling."""
    patterns: dict[str, tuple[str, ...]] = {
        "OPEN_PATIENT": (
            r"^(?:افتح|فتح)\s+(?:حالة|حاله|ملف)\s+(.+)$",
            r"^open\s+(?:patient|case)\s+(.+)$",
        ),
        "SEARCH_PATIENT": (
            r"^(?:ابحث|دور)\s+(?:عن\s+)?(?:مريض\s+)?(.+)$",
            r"^search\s+(?:for\s+)?(?:patient\s+)?(.+)$",
        ),
        "OPEN_CBCT": (
            r"(?:\s+بتاع|\s+للمريض|\s+ل)\s+(.+)$",
            r"\s+(?:for|of)\s+(.+)$",
        ),
    }
    for pattern in patterns.get(command, ()):
        match = re.search(pattern, raw_step, flags=re.IGNORECASE)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def interpret(
    transcript: str,
    context: VoiceUIContext | None = None,
) -> list[VoiceCommandPlan]:
    del context
    plans: list[VoiceCommandPlan] = []
    for raw_step in split_steps(transcript):
        step = normalize_text(raw_step)
        matched: tuple[VoiceCommandSpec, object, float] | None = None
        for spec in COMMANDS:
            match, score = _pattern_match(spec, step)
            if match:
                matched = (spec, match, score)
                break
        if matched is None:
            ranked = sorted(
                ((_fuzzy_score(spec, step), spec) for spec in COMMANDS),
                reverse=True,
                key=lambda item: item[0],
            )
            score, spec = ranked[0]
            second_score = ranked[1][0] if len(ranked) > 1 else 0.0
            if score < _MEDIUM:
                plans.append(
                    VoiceCommandPlan(
                        command="UNKNOWN",
                        confidence=score,
                        risk="read",
                        available=False,
                        blocked_reason="Command not recognized with sufficient confidence.",
                    )
                )
                continue
            if score - second_score < _FUZZY_AMBIGUITY_MARGIN:
                plans.append(
                    VoiceCommandPlan(
                        command="UNKNOWN",
                        confidence=score,
                        risk="read",
                        available=False,
                        blocked_reason="Ambiguous fuzzy command match; clarification required.",
                    )
                )
                continue
            matched = (spec, None, score)

        spec, match, confidence = matched
        entities: dict[str, str] = {}
        if match is not None:
            entities = {
                key: value.strip()
                for key, value in match.groupdict().items()
                if value and value.strip()
            }
            raw_patient = _raw_patient_name(spec.name, raw_step)
            if raw_patient is not None and "patient_name" in entities:
                entities["patient_name"] = raw_patient

        requires_confirmation = spec.risk.value in {"mutation", "destructive"}
        plans.append(
            VoiceCommandPlan(
                command=spec.name,
                entities=entities,
                confidence=confidence,
                risk=spec.risk,
                available=spec.available,
                blocked_reason=spec.blocked_reason,
                requires_confirmation=requires_confirmation,
            )
        )
    return plans


def confidence_requires_clarification(plan: VoiceCommandPlan) -> bool:
    if plan.command == "UNKNOWN" or plan.confidence < _MEDIUM:
        return True
    if plan.confidence < _HIGH:
        return True
    if plan.risk.value in {"mutation", "destructive"}:
        return True
    return False
