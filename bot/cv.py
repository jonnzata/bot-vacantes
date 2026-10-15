"""Lee la hoja de vida y detecta las habilidades técnicas que contiene, para
puntuar cada vacante según cuánto se parece a tu perfil."""
import logging
import os
from pathlib import Path

from .text import matched_terms, normalize

log = logging.getLogger(__name__)

# Diccionario de habilidades de sistemas. Solo cuentan las que estén en tu HV.
SKILLS = [
    "python", "java", "javascript", "typescript", "c#", ".net", "php", "go", "kotlin",
    "swift", "dart", "flutter", "react", "angular", "vue", "node", "django", "flask",
    "spring", "laravel", "html", "css", "sql", "mysql", "postgresql", "sql server",
    "oracle", "mongodb", "firebase", "sqlite", "power bi", "excel", "git", "github",
    "docker", "kubernetes", "linux", "windows server", "active directory", "aws",
    "azure", "google cloud", "gcp", "terraform", "jenkins", "ci/cd", "scrum", "agile",
    "jira", "itil", "cisco", "ccna", "mikrotik", "fortinet", "firewall", "vpn", "tcp/ip",
    "lan", "wan", "dns", "dhcp", "vmware", "virtualizacion", "redes", "cableado estructurado",
    "soporte tecnico", "mesa de ayuda", "mantenimiento de equipos", "hardware", "office 365",
    "microsoft 365", "sap", "erp", "api", "rest", "microservicios", "android", "ios",
    "seguridad informatica", "ciberseguridad", "pentesting", "qa", "selenium", "pruebas",
    "analisis de datos", "machine learning", "inteligencia artificial", "bash", "powershell",
]


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def load_cv_text(path: str, base_dir: Path) -> str:
    env_text = os.environ.get("CV_TEXT", "")
    if env_text.strip():
        return env_text
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists():
        log.warning("No se encontró la hoja de vida en %s (se puntúa solo con el área)", p)
        return ""
    return _read_pdf(p) if p.suffix.lower() == ".pdf" else p.read_text(encoding="utf-8", errors="ignore")


def extract_skills(cv_text: str) -> list:
    return matched_terms(normalize(cv_text), SKILLS)
