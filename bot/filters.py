import re
from datetime import date, timedelta

from .models import Job
from .text import matched_terms, normalize

REMOTE_TERMS = ["remoto", "teletrabajo", "home office", "trabajo desde casa", "100% remoto"]


class JobFilter:
    def __init__(self, config: dict, cv_skills: list):
        self.towns = config["ubicacion"]["municipios"]
        self.allow_remote = config["ubicacion"].get("incluir_remoto", False)
        self.include = config["area"]["incluir"]
        self.exclude = config["area"].get("excluir", [])
        run = config.get("ejecucion", {})
        self.min_score = run.get("min_puntaje", 3)
        self.max_days = run.get("dias_maximos", 0)
        self.cv_skills = cv_skills

    def title_ok(self, job: Job) -> bool:
        """Filtro rápido (antes de descargar el detalle): descarta títulos excluidos."""
        return not matched_terms(normalize(job.title), self.exclude)

    def in_antioquia(self, job: Job) -> bool:
        # Se prioriza el campo de ubicación; solo si está vacío se mira el texto.
        where = normalize(job.location) or normalize(job.description[:600])
        if matched_terms(where, self.towns):
            return True
        if self.allow_remote:
            return bool(matched_terms(normalize(f"{job.title} {job.location}"), REMOTE_TERMS))
        return False

    def is_recent(self, job: Job) -> bool:
        if not self.max_days or not job.published:
            return True
        # Algunos portales envían fechas sin ceros (ej. elempleo: "2026-8-26").
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", job.published)
        try:
            published = date(int(m[1]), int(m[2]), int(m[3])) if m else None
        except ValueError:
            published = None
        if published is None:
            return True
        return published >= date.today() - timedelta(days=self.max_days)

    def score(self, job: Job) -> int:
        title = normalize(job.title)
        desc = normalize(job.description)
        title_hits = matched_terms(title, self.include)
        desc_hits = matched_terms(desc, self.include)
        if not title_hits and len(desc_hits) < 2:
            return 0  # no es de sistemas
        job.matched_skills = matched_terms(f"{title} {desc}", self.cv_skills)
        return 3 * len(title_hits) + len(desc_hits) + 2 * len(job.matched_skills)

    def reject_reason(self, job: Job):
        """None si la vacante pasa; si no, el motivo del descarte."""
        if not self.title_ok(job):
            return "titulo excluido"
        if not self.in_antioquia(job):
            return "fuera de Antioquia"
        if not self.is_recent(job):
            return "antigua"
        job.score = self.score(job)
        if job.score == 0:
            return "no es de sistemas"
        if job.score < self.min_score:
            return "puntaje bajo"
        return None

    def accept(self, job: Job) -> bool:
        return self.reject_reason(job) is None
