"""Local deterministic intent recognition for Dentora Voice."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .normalization import normalize_text
from .registry import COMMANDS, VoiceCommandSpec
from .schemas import VoiceCommandPlan, VoiceUIContext

_HIGH = 0.85
_MEDIUM = 0.60

_STEP_SPLIT = re.compile(
    r"\s+(?:ثم|وبعدين|بعدها|then|and then)\s+|"
    r"\s+و(?=(?:اعرض|اظهر|افتح|شغل|قارن)\b)|"
    r"\s+and\s+(?=(?:show|open|compare|go)\b)"
)

def split_steps(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [part.strip() for part in _STEP_SPLIT.split(normalized) if part.strip()]

def _pattern_match(spec: VoiceCommandSpec, step: str):
    for pattern in spec.patterns:
        match = pattern.fullmatch(step)
        if match:
            return match, 0.98
    return None, 0.0

def _fuzzy_score(spec: VoiceCommandSpec, step: str) -> float:
    best = 0.0
    for pattern in spec.patterns:
        hint = re.sub(r"[\^\$\(\)\?\:\[\]\+\*\|\\]", " ", pattern.pattern)
        hint = re.sub(r"\?P<[^>]+>", " ", hint)
        hint = normalize_text(hint)
        best = max(best, SequenceMatcher(None, step, hint).ratio())
    return round(best * 0.82, 3)

def interpret(transcript: str, context: VoiceUIContext | None = None) -> list[VoiceCommandPlan]:
    del context
    plans: list[VoiceCommandPlan] = []
    for step in split_steps(transcript):
        matched: tuple[VoiceCommandSpec, object, float] | None = None
        for spec in COMMANDS:
            match, score = _pattern_match(spec, step)
            if match:
                matched = (spec, match, score)
                break
        if matched is None:
            ranked = sorted(((_fuzzy_score(spec, step), spec) for spec in COMMANDS), reverse=True, key=lambda x: x[0])
            score, spec = ranked[0]
            if score < _MEDIUM:
                plans.append(VoiceCommandPlan(
                    command="UNKNOWN", confidence=score, risk="read", available=False,
                    blocked_reason="Command not recognized with sufficient confidence."
                ))
                continue
            matched = (spec, None, score)

        spec, match, confidence = matched
        entities = {}
        if match is not None:
            entities = {k: v.strip() for k, v in match.groupdict().items() if v and v.strip()}
        requires_confirmation = spec.risk.value in {"mutation", "destructive"}
        plans.append(VoiceCommandPlan(
            command=spec.name,
            entities=entities,
            confidence=confidence,
            risk=spec.risk,
            available=spec.available,
            blocked_reason=spec.blocked_reason,
            requires_confirmation=requires_confirmation,
        ))
    return plans

def confidence_requires_clarification(plan: VoiceCommandPlan) -> bool:
    if plan.command == "UNKNOWN" or plan.confidence < _MEDIUM:
        return True
    if plan.confidence < _HIGH:
        return True
    if plan.risk.value in {"mutation", "destructive"}:
        return True
    return False
