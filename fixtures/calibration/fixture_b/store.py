"""EventStore implementation for Fixture B."""
import json
import pathlib
from models import Event


class EventStore:
    def __init__(self, storage_path: pathlib.Path):
        self.storage_path = pathlib.Path(storage_path)
        self._index = {}  # type -> list of Event
        self._load()

    def _load(self):
        if not self.storage_path.exists():
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ev = Event.from_dict(json.loads(line))
                    self._index.setdefault(ev.event_type, []).append(ev)

    def append(self, event: Event):
        with open(self.storage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
        self._index.setdefault(event.event_type, []).append(event)

    def query_by_type(self, event_type: str) -> list[Event]:
        return list(self._index.get(event_type, []))
