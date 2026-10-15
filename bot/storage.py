"""Registro de vacantes ya enviadas, para no repetirlas."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path, keep_days: int = 90):
        self.path = path
        self.keep_days = keep_days
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except json.JSONDecodeError:
                self.data = {}

    def __contains__(self, uid: str) -> bool:
        return uid in self.data

    def add(self, uid: str) -> None:
        self.data[uid] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def save(self) -> None:
        limit = datetime.now(timezone.utc) - timedelta(days=self.keep_days)
        self.data = {k: v for k, v in self.data.items() if datetime.fromisoformat(v) >= limit}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0))
