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
        try:
            published = date.fromisoformat(job.published[:10])
        except ValueError:
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

    def accept(self, job: Job) -> bool:
        if not (self.title_ok(job) and self.in_antioquia(job) and self.is_recent(job)):
            return False
        job.score = self.score(job)
        return job.score >= self.min_score
