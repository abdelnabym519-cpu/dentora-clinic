"""Planning provider abstraction + fail-closed registry.

The provider layer is the *only* place a model (today the deterministic
reference planner; tomorrow a learned ML/RL policy) touches the system:

* :class:`PlanningProvider` is a plain Protocol — the service layer has
  no dependency on any provider implementation.
* Providers are registered by name and resolved from
  ``settings.ORTHO_PLANNING_PROVIDER``. An unknown or broken provider
  raises :class:`ProviderUnavailableError`, which the API maps to HTTP
  503 — the system fails closed, it never silently falls back.
* Whatever a provider returns is *always* re-validated by the
  deterministic constraint layer before persistence
  (``constraints.evaluate_stages``); a provider output that violates a
  hard safety bound is refused and audited, never stored.

RL honesty note: there is **no trained policy and no shipped weights**
in this repository — no orthodontic outcome dataset exists to train one
honestly. The protocol, the deterministic transition/reward semantics
(``domain``, ``constraints``, ``planner.heuristic.score_proposal``) and
this registry are the extension point an offline-trained policy plugs
into once curated outcome data exists.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import settings

from ..constants import ORTHO_PLANNING_PROVIDER_SETTING, PROVIDER_HEURISTIC
from ..domain import InsufficientDataError, PlannerCase, Stage

__all__ = [
    "InsufficientDataError",
    "PlanSuggestion",
    "PlanningProvider",
    "ProviderRegistryError",
    "ProviderUnavailableError",
    "get_provider",
    "register_provider",
]

logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """Raised when the configured provider cannot be resolved/loaded."""


class ProviderRegistryError(RuntimeError):
    """Raised on invalid provider registration (duplicate/bad factory)."""


@runtime_checkable
class PlanningProvider(Protocol):
    """A plan proposal source.

    Implementations MUST be deterministic or explicitly quantify their
    uncertainty via ``PlanSuggestion.confidence`` + ``uncertainty``.
    Implementations MUST NOT persist anything and MUST NOT perform any
    mutation — they only *propose*.
    """

    name: str
    version: str

    def propose_plan(self, case: PlannerCase) -> PlanSuggestion: ...


@dataclass(frozen=True)
class PlanSuggestion:
    """Provider output before persistence + independent re-validation."""

    stages: tuple[Stage, ...]
    provider: str
    provider_version: str
    score: float  # deterministic reward in [0, 1] (see heuristic.score_proposal)
    confidence: float  # provider self-reported certainty in [0, 1]
    uncertainty: tuple[str, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be within [0, 1]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")


# --- Registry ------------------------------------------------------------------

ProviderFactory = Callable[[], PlanningProvider]

_REGISTRY: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a provider factory under ``name`` (idempotent)."""
    if not name:
        raise ProviderRegistryError("Provider name must be non-empty")
    if not callable(factory):
        raise ProviderRegistryError(f"Provider factory for '{name}' must be callable")
    _REGISTRY[name] = factory


def _known_providers() -> dict[str, ProviderFactory]:
    """Registry including the built-in reference planner."""
    from . import heuristic  # local import avoids a circular dependency

    providers = dict(_REGISTRY)
    providers.setdefault(heuristic.PROVIDER_NAME, heuristic.HeuristicPlanner)
    return providers


def get_provider(name: str | None = None) -> PlanningProvider:
    """Resolve a provider by name (default: settings), fail-closed.

    Raises:
        ProviderUnavailableError: unknown name or factory failure.
    """
    resolved = (name or getattr(settings, ORTHO_PLANNING_PROVIDER_SETTING, "")).strip()
    if not resolved:
        raise ProviderUnavailableError(
            f"No orthodontic planning provider configured "
            f"({ORTHO_PLANNING_PROVIDER_SETTING} is empty)"
        )
    factory = _known_providers().get(resolved)
    if factory is None:
        raise ProviderUnavailableError(
            f"Unknown orthodontic planning provider '{resolved}'. "
            f"Known providers: {sorted(_known_providers())}"
        )
    try:
        provider = factory()
    except Exception as exc:  # noqa: BLE001 — fail closed on any factory failure
        raise ProviderUnavailableError(
            f"Provider '{resolved}' failed to initialize: {exc}"
        ) from exc
    if not isinstance(provider, PlanningProvider):
        raise ProviderUnavailableError(
            f"Provider '{resolved}' does not satisfy the PlanningProvider protocol"
        )
    logger.debug("Resolved orthodontic planning provider '%s'", resolved)
    return provider


# Default provider name re-exported for settings/docs convenience.
DEFAULT_PROVIDER = PROVIDER_HEURISTIC
