import re
from datetime import date, timedelta

from .models import Job
from .text import matched_terms, normalize, remove_terms

REMOTE_TERMS = ["remoto", "remota", "teletrabajo", "home office", "trabajo desde casa", "100% remoto",
                "remote", "fully remote", "work from home"]
# Si el título o la ubicación dicen esto, no es teletrabajo completo.
NOT_REMOTE_TERMS = ["presencial", "hibrido", "hibrida", "hybrid", "on-site", "onsite"]
# Palabras que se quitan de la ubicación de una vacante remota antes de ver la región.
_REMOTE_NOISE = sorted(REMOTE_TERMS + ["remoto desde", "remote from", "desde", "from", "only", "solo",
                                       "anywhere in the world"], key=len, reverse=True)
# Desde esta longitud se considera que la vacante trae descripción completa (y no
# solo la tarjeta de un listado o de un correo de alerta).
FULL_DESCRIPTION_CHARS = 300


class JobFilter:
    def __init__(self, config: dict, cv_skills: list):
        self.towns = config["ubicacion"]["municipios"]
        self.allow_remote = config["ubicacion"].get("incluir_remoto", False)
        self.remote_regions = config["ubicacion"].get("regiones_remoto", ["colombia"])
        self.include = config["area"]["incluir"]
        self.include_title = config["area"].get("incluir_titulo", [])
        self.ignore = config["area"].get("ignorar", [])
        self.exclude = config["area"].get("excluir", [])
        self.exclude_desc = config["area"].get("excluir_descripcion", [])
        run = config.get("ejecucion", {})
        self.min_score = run.get("min_puntaje", 3)
        self.max_days = run.get("dias_maximos", 0)
        self.cv_skills = cv_skills

    def title_ok(self, job: Job) -> bool:
        """Filtro rápido (antes de descargar el detalle): descarta títulos excluidos."""
        return not matched_terms(normalize(job.title), self.exclude)

    def in_antioquia(self, job: Job) -> bool:
        # Se prioriza el campo de ubicación; solo si está vacío se mira el texto.
        where = normalize(job.location) or normalize(job.description[:1500])
        if matched_terms(where, self.towns):
            return True
        return self.allow_remote and self.remote_ok(job)

    def remote_ok(self, job: Job) -> bool:
        """Teletrabajo que se puede hacer desde Colombia."""
        head = normalize(f"{job.title} {job.location}")
        if matched_terms(head, NOT_REMOTE_TERMS):
            return False
        if job.remote:
            # Portal de teletrabajo (a menudo internacional): la región que exige la
            # vacante debe estar vacía o ser global / LatAm / Colombia.
            region = re.sub(r"[^a-z]+", " ", remove_terms(normalize(job.location), _REMOTE_NOISE)).strip()
            return not region or bool(matched_terms(region, self.remote_regions))
        # Portales colombianos: basta con que diga remoto y no sea híbrido/presencial.
        text = normalize(job.description[:600])
        return bool(matched_terms(f"{head} {text}", REMOTE_TERMS)) and not matched_terms(text, NOT_REMOTE_TERMS)

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
        title = remove_terms(normalize(job.title), self.ignore)
        desc = remove_terms(normalize(job.description), self.ignore)
        title_hits = matched_terms(title, self.include)
        weak_hits = matched_terms(title, self.include_title)
        desc_hits = matched_terms(desc, self.include)
        if not title_hits:
            if weak_hits:
                # Título ambiguo ("Analista de redes", "Ingeniero de infraestructura"):
                # si hay descripción completa, debe confirmar que es de sistemas.
                if len(desc) >= FULL_DESCRIPTION_CHARS and not desc_hits:
                    return 0
            elif len(desc_hits) < 2:
                return 0  # no es de sistemas
        job.matched_skills = matched_terms(f"{title} {desc}", self.cv_skills)
        return 3 * len(title_hits + weak_hits) + len(desc_hits) + 2 * len(job.matched_skills)

    def reject_reason(self, job: Job):
        """None si la vacante pasa; si no, el motivo del descarte."""
        if not self.title_ok(job):
            return "titulo excluido"
        if matched_terms(normalize(job.description), self.exclude_desc):
            return "aprendiz o practica"
        if not self.in_antioquia(job):
            return "fuera de Antioquia y no es remota desde Colombia"
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
