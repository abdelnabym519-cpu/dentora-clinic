# 0019 — Clean Architecture as a mandatory acceptance criterion

- **Status:** accepted
- **Date:** 2026-08-23
- **Deciders:** Mohamed Abdelnaby (maintainer), Dentora core team
- **Tags:** architecture, governance, modules, ai, clinical-safety

## Context

Dentora's roadmap moves into 3D and AI-heavy territory (tooth segmentation,
nerve detection, pathology detection, implant/surgical planning, Digital
Twin, case intelligence, dentist copilot). These capabilities bring
fast-moving external dependencies — LLM providers, inference runtimes,
mesh/vision models — exactly the kind of technology that gets replaced on a
different cadence than clinical business rules.

The codebase already has Clean-Architecture-shaped seams: thin routers over
static service classes, the vendor-neutral `Provider` protocol in
`app/core/llm/base.py` (one live adapter: OpenAI), the agent tool registry,
the event bus (ADR 0003), per-module isolation (ADR 0001/0002) and the
frontend slot registry. Nothing, however, makes the layering a **rule** a
reviewer or agent can point to when a phase proposes coupling domain logic
to a framework.

## Decision

**Clean Architecture is a mandatory acceptance criterion for every new
Dentora feature and module.** A phase is NOT complete if its functionality
works but violates the architecture boundary.

### Dependency direction (inward only)

```
Presentation  →  Application  →  Domain
                     ↑                ↑
        Infrastructure implements interfaces/ports
        defined by the inner layers
```

- **Domain** — entities, value objects, domain rules, domain services,
  repository interfaces/ports, domain contracts. Must not depend on FastAPI,
  SQLAlchemy, PostgreSQL, Nuxt, Vue, Three.js, AI/LLM providers, external
  APIs, storage providers, or any framework-specific infrastructure.
- **Application** — use cases, application services, commands, queries,
  orchestration, application policies. Depends on domain abstractions, not
  concrete infrastructure.
- **Infrastructure** — SQLAlchemy repositories, database persistence,
  external APIs, AI/ML providers, storage, messaging, third-party services.
  Implements interfaces defined by domain/application.
- **Presentation** — API routers/controllers, request/response DTOs,
  auth adapters, frontend adapters. No core business rules.

### Dependency inversion for external capabilities

When a use case needs an external capability, define the abstraction at the
inner boundary (e.g. an `ImplantPlanner` interface in the application
layer) and swap adapters in infrastructure (`AIImplantPlanner`,
`RuleBasedImplantPlanner`, `FutureMLImplantPlanner`). The application must
never depend on a specific provider or model.

### AI architecture rule

All AI features are replaceable infrastructure:

```
Application use case → AI/ML interface → infrastructure adapter → model/provider
```

Business/application code must not depend on OpenAI, Anthropic, local LLMs,
PyTorch, TensorFlow, specific segmentation models or inference servers.
`app/core/llm/` (neutral types + `Provider` protocol) is the existing
template for this pattern.

### Clinical safety boundary

Clinical AI is **decision support only**:

```
AI analysis → evidence/measurements → recommendation/finding
            → dentist review → dentist decision
```

Never architect autonomous clinical decision-making. AI output types are
findings/recommendations with evidence, gated by dentist review — never
final clinical state.

### Existing codebase

Do **not** rewrite Dentora and do not migrate modules wholesale. When an
existing module is modified in a future phase: preserve behavior, refactor
incrementally only where necessary, keep changes minimal, keep tests green,
and validate before/after. Never refactor for aesthetics only. Legacy
coupling (e.g. services taking `AsyncSession` directly) is acknowledged
debt, addressed on-touch — not a blocker for review of unrelated work.

### New module standard

Conceptual separation is mandatory; exact folder names follow the module's
complexity and existing repo conventions (`schemas.py`/`service.py`/
`router.py` files for simple modules; explicit `domain/`, `application/`,
`infrastructure/`, `presentation/` subpackages when a module earns them):

```
module/
├── domain/          # or schemas.py — entities, ports, invariants
├── application/     # or service.py — use cases, orchestration
├── infrastructure/  # or models.py + adapters — persistence, providers
├── presentation/    # router.py, tools.py, frontend/ layer
└── tests/
```

## Consequences

### Good

- Providers/models can be replaced without touching clinical or application
  logic; AI vendors become configuration, not architecture.
- Domain rules (FDI vocabulary, scene contracts, clinical-safety guards)
  become testable without frameworks or databases.
- Reviewers and agents have an explicit, citable gate for phase acceptance.
- Matches seams that already exist (`app/core/llm`, tool registry, event
  bus) — the rule formalizes practice, it does not fork it.

### Bad / accepted trade-offs

- More files/indirection for small modules; mitigated by the
  complexity-scaled structure above (no forced folders for trivial modules).
- Existing modules do not comply yet; compliance is forward-looking and
  incremental, which means two styles coexist for a while.

## Alternatives considered

- **Adopt Hexagonal/Onion naming instead** — same principle, different
  vocabulary; "Clean Architecture" chosen for recognizability. Rejected as
  a distinction without a difference here.
- **Enforce by folder convention + import-linter in CI from day one** —
  desirable long-term (see verification below) but would fail the entire
  legacy codebase immediately; deferred until enough new-style modules
  exist to make a lint rule meaningful.
- **Rewrite existing modules to comply** — rejected: high risk, no behavior
  gain, violates the minimal-change posture (and this ADR's own rules).

## How to verify the rule still holds

- Phase acceptance checklist (all boxes required):
  - [ ] Clean Architecture compliance
  - [ ] Correct dependency direction
  - [ ] Domain independent of frameworks
  - [ ] Business logic isolated from infrastructure
  - [ ] Dependency inversion where appropriate
  - [ ] Existing architecture preserved
  - [ ] No unnecessary refactoring
  - [ ] Tests added/updated
  - [ ] Existing tests remain green
  - [ ] Module isolation preserved
  - [ ] Clinic isolation preserved
  - [ ] Security/RBAC preserved
  - [ ] Documentation updated
  - [ ] CI validation passed
- Spot checks for new modules: `grep -r "fastapi\|sqlalchemy" <module>/domain/`
  (must be empty); AI interfaces defined without provider imports; adapters
  referenced through the interface only.
- First `dental_3d` mapping (Phase 1 review, no refactor performed) lives in
  `docs/technical/dental_3d/overview.md` + the phase-1 engineering notes.

## References

- `backend/app/core/llm/base.py` — existing vendor-neutral Provider protocol
- `docs/adr/0001-modular-plugin-architecture.md`,
  `docs/adr/0002-per-module-alembic-branches.md`,
  `docs/adr/0003-event-bus-over-direct-imports.md` — module boundaries
- `CLAUDE.md` — "Modular architecture (read first)" hard rules
- `docs/technical/creating-modules.md` — module author guide (layer mapping)
- `docs/technical/dental_3d/overview.md` — first module reviewed under this ADR
