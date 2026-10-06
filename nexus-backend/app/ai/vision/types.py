from dataclasses import dataclass

from app.ai.vision.schemas import FrameReference


@dataclass(frozen=True)
class FramePacket[FramePayloadT]:
    """A frame payload paired with validated, stable frame metadata."""

    reference: FrameReference
    payload: FramePayloadT
