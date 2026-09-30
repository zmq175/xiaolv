"""Validated image bytes prepared for an explicit vision request."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    width: int
    height: int
    original_frames: int
    content_type: str = "image/jpeg"
    sampled_frames: tuple[int, ...] = (0,)
