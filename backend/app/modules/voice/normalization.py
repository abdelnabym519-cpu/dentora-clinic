"""Deterministic text normalization for Dentora Voice.

No network calls, no LLMs, and no clinical interpretation.
"""
from __future__ import annotations

import re
import unicodedata

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_PUNCT = re.compile(r"[^\w\s\u0600-\u06ff]+", re.UNICODE)
_SPACES = re.compile(r"\s+")

_TRANSLATION = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ؤ": "و", "ئ": "ي", "ة": "ه",
    "ـ": "",
})

def normalize_text(value: str) -> str:
    """Return a stable Arabic/English matching representation."""
    value = unicodedata.normalize("NFKC", value or "")
    value = _ARABIC_DIACRITICS.sub("", value)
    value = value.translate(_TRANSLATION).casefold()
    value = _PUNCT.sub(" ", value)
    return _SPACES.sub(" ", value).strip()

def safe_preview(value: str, *, limit: int = 96) -> str:
    """Ephemeral UI preview helper; never intended for server logging."""
    compact = _SPACES.sub(" ", (value or "").strip())
    return compact[:limit]
