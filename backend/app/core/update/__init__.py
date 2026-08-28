"""Dentora update validation boundary."""

from .application import validate_update
from .domain import UpdateDescriptor, UpdateValidationError

__all__ = ["UpdateDescriptor", "UpdateValidationError", "validate_update"]
