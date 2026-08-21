"""Fuzzy matching for the catalog mapper.

Pure-function coverage of ``_normalise`` and ``_token_match_score``.
The DB-backed ``_find_match`` is exercised end-to-end by the importer
integration tests; here we lock in the behaviour of the helpers that
drive it.
"""

from __future__ import annotations

from app.modules.migration_import.mappers.catalog import (
    _FUZZY_MATCH_THRESHOLD,
    _normalise,
    _token_match_score,
)


def test_normalise_strips_accents() -> None:
    assert _normalise("Obturación composite") == "obturacion composite"
    assert _normalise("Endodoncia molar") == "endodoncia molar"


def test_normalise_collapses_punctuation_and_whitespace() -> None:
    assert _normalise("OBTUR. COMP.") == "obtur comp"
    assert _normalise("Corona  metal-cerámica") == "corona metal ceramica"
    assert _normalise("  ENDODONCIA   UNI.  ") == "endodoncia uni"


def test_normalise_empty_and_none_safe() -> None:
    assert _normalise("") == ""
    assert _normalise(None) == ""


def test_fuzzy_accepts_gesden_abbreviations() -> None:
    """Common Gesdén-side abbreviations must clear the threshold against
    the canonical Dentora seed labels."""
    pairs_that_must_match = [
        ("obtur composite", "obturacion composite"),
        ("endodoncia uni", "endodoncia unirradicular"),
        ("corona zirc", "corona zirconio"),
        ("impl titanio", "implante de titanio"),
    ]
    for src, dst in pairs_that_must_match:
        score = _token_match_score(src, dst)
        assert score >= _FUZZY_MATCH_THRESHOLD, (src, dst, score)


def test_fuzzy_rejects_different_treatments() -> None:
    """Cousin treatments with one swapped token must NOT cross the
    threshold or we'd mis-link materials/types."""
    pairs_that_must_reject = [
        ("corona metal", "corona zirconio"),
        ("endodoncia uni", "endodoncia molar"),
        ("obturacion composite", "obturacion amalgama"),
        # Bare "corona" is ambiguous across many crown variants; the
        # extra unmatched destination tokens drop the score.
        ("corona", "corona zirconio"),
    ]
    for src, dst in pairs_that_must_reject:
        score = _token_match_score(src, dst)
        assert score < _FUZZY_MATCH_THRESHOLD, (src, dst, score)


def test_fuzzy_prefers_exact_token_set_over_supersets() -> None:
    """Source "corona metal" must score strictly higher against the
    exact "corona metal" destination than against "corona metal
    cerámica" — otherwise we'd swallow distinct cousin treatments."""
    src = "corona metal"
    exact_score = _token_match_score(src, "corona metal")
    superset_score = _token_match_score(src, "corona metal ceramica")
    assert exact_score > superset_score
    assert exact_score >= _FUZZY_MATCH_THRESHOLD
    assert superset_score < _FUZZY_MATCH_THRESHOLD
