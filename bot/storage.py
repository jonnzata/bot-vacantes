"""Registro de vacantes ya enviadas, para no repetirlas."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Las postulaciones se recuerdan más tiempo que las vacantes vistas.
LONG_PREFIXES = ("postulada",)
LONG_DAYS = 365


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

    # Última consulta de cada fuente (para las que piden no consultarlas cada hora).
    def last_run(self, source: str):
        value = self.data.get(f"fuente:{source}")
        return datetime.fromisoformat(value) if value else None

    def mark_run(self, source: str) -> None:
        self.add(f"fuente:{source}")

    def save(self) -> None:
        now = datetime.now(timezone.utc)
        limit, long_limit = now - timedelta(days=self.keep_days), now - timedelta(days=LONG_DAYS)
        self.data = {k: v for k, v in self.data.items()
                     if datetime.fromisoformat(v) >= (long_limit if k.startswith(LONG_PREFIXES) else limit)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=0))
