"""Humanizer filter — comprehensive AI-tell scrubbing pipeline.

Every outbound message flows through this before style mirroring.
Based on the 33+ AI writing patterns documented in the humanizer skill.
"""

from .filter import HumanizerFilter

__all__ = ["HumanizerFilter"]