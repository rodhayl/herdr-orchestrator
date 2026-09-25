"""Data models for Fixture B Event Store."""
import dataclasses
import json
import time


@dataclasses.dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    payload: dict
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            payload=data["payload"],
            timestamp=data.get("timestamp", 0.0)
        )
