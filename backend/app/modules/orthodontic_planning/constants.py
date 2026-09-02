"""Clinical constants for orthodontic planning (decision support).

Every number in this file is a **conservative, documented default** used
by the deterministic constraint layer and the reference planner. They
are deliberately visible in one place so clinics and auditors can
review the exact safety envelope a plan was generated under.

``CONSTRAINTS_VERSION`` is stamped onto every persisted proposal so an
audit trail can always answer "which bound set produced this plan?".
"""

from __future__ import annotations

# Version stamp persisted on every proposal (audit trail).
CONSTRAINTS_VERSION = "ortho-constraints-2026.09"

# --- Provider registry ------------------------------------------------------

# Default (and only shipped) planning provider: the deterministic
# reference planner. Learned policies register under different names;
# an unknown configured name fails closed (see planner/base.py).
PROVIDER_HEURISTIC = "heuristic_v1"
ORTHO_PLANNING_PROVIDER_SETTING = "ORTHO_PLANNING_PROVIDER"

# --- Movement types and safety bounds ----------------------------------------

# Per-stage caps keep any single activation biologically conservative;
# per-tooth totals cap the cumulative movement a v1 plan may propose.
# (magnitude units: mm for translations, degrees for angular moves)
MOVEMENT_LIMITS: dict[str, dict[str, float]] = {
    "intrusion": {"per_stage": 0.5, "per_tooth_total": 4.0},
    "extrusion": {"per_stage": 0.5, "per_tooth_total": 4.0},
    "proclination": {"per_stage": 0.5, "per_tooth_total": 6.0},
    "retroclination": {"per_stage": 0.5, "per_tooth_total": 6.0},
    "mesialization": {"per_stage": 0.5, "per_tooth_total": 5.0},
    "distalization": {"per_stage": 0.5, "per_tooth_total": 5.0},
    "rotation_correction": {"per_stage": 10.0, "per_tooth_total": 45.0},
    "torque": {"per_stage": 5.0, "per_tooth_total": 25.0},
    "uprighting": {"per_stage": 5.0, "per_tooth_total": 30.0},
}

# Non-extraction space envelope (per arch, mm of arch-length relief the
# v1 model may credit): incisor proclination gain and first-molar
# distalization. Anything beyond this is flagged for specialist decision
# (extraction / transverse / surgical options are outside v1).
PROCLINATION_SPACE_GAIN_PER_MM = 1.0
MAX_UPPER_PROCLINATION_MM = 3.0
MAX_LOWER_PROCLINATION_MM = 2.0
MOLAR_DISTALIZATION_MAX_PER_SIDE_MM = 1.0

# Overjet envelope: planned upper-incisor retroclination beyond this is
# a hard violation (non-surgical correction envelope).
TARGET_OVERJET_MM = 3.0
MAX_OVERJET_REDUCTION_MM = 6.0

# Plan shape.
MAX_STAGES = 30
MIN_STAGES = 1
STAGE_INTERVAL_WEEKS = 6
WEEKS_PER_MONTH = 4.345

# --- Assessment / data sufficiency -------------------------------------------

SKELETAL_PATTERNS = ("class_i", "class_ii", "class_iii")
GROWTH_STAGES = ("adolescent", "adult")
RELATIONS = ("class_i", "class_ii", "class_iii")
OBJECTIVES = (
    "align",
    "correct_overjet",
    "correct_overbite",
    "correct_crossbite",
    "space_management",
)

# Required clinician-entered measurements before any plan may be
# generated (fail-closed: the planner refuses and lists the gaps).
REQUIRED_MEASUREMENTS = (
    "skeletal_pattern",
    "growth_stage",
    "overjet_mm",
    "overbite_mm",
    "crowding_upper_mm",
    "crowding_lower_mm",
    "molar_relation_left",
    "molar_relation_right",
    "canine_relation_left",
    "canine_relation_right",
)

# Odontogram coverage required for planning: the snapshot must chart at
# least this many permanent teeth, otherwise the case is considered
# under-documented and planning fails closed.
MIN_CHARTED_PERMANENT_TEETH = 20

# Odontogram ``general_condition`` values that mean "no tooth present".
MISSING_TOOTH_CONDITIONS = ("missing", "extracted")

# --- Proposal lifecycle -------------------------------------------------------

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
PROPOSAL_STATUSES = (STATUS_DRAFT, STATUS_APPROVED, STATUS_REJECTED)
REVIEW_DECISIONS = (STATUS_APPROVED, STATUS_REJECTED)

# --- Deterministic scoring (reward specification) ------------------------------

# The planner scores every proposal with a transparent, fixed weighting.
# This function doubles as the reward specification for any future
# learned policy: training must optimize *this* function plus the hard
# constraint gate, not an unspecified proxy.
SCORE_WEIGHT_ALIGNMENT = 0.6
SCORE_WEIGHT_ENVELOPE = 0.25
SCORE_WEIGHT_STAGE_EFFICIENCY = 0.15

# The deterministic reference policy models no biomechanics, so its
# self-reported confidence is capped below 1.0.
HEURISTIC_MAX_CONFIDENCE = 0.9

# Magnitudes below this are treated as zero when composing streams.
EPSILON_MM = 0.05
