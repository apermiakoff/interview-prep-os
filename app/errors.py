"""Domain errors shared across service modules.

Defined here (not in app.services) so low-level modules like app.attempts can
raise them without importing the service layer that imports those modules.
"""

from __future__ import annotations


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass
