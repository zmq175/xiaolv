"""Stable execution denial codes without policy backend details."""

from typing import Literal


class PermissionDenied(Exception):
    def __init__(self, reason: Literal["permission_denied", "permission_error"]) -> None:
        self.reason = reason
        super().__init__(reason)
