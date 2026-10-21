"""Portales de empleo REMOTO con API o RSS públicos (no hace falta scraping).

Cada portal se consulta una sola vez por ejecución (salvo Get on Board, que
acepta búsquedas) y devuelve vacantes marcadas como remotas. El filtro decide
después si son de sistemas y si se pueden hacer desde Colombia.

Sus condiciones de uso piden enlazar a la oferta original y citar el portal:
por eso cada vacante lleva su URL y el nombre del portal en `source`."""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..models import Job
from ..text import html_to_text

log = logging.getLogger(__name__)


def _iso(value) -> str:
    """Convierte fechas ISO, RFC 822 (RSS) o marcas de tiempo Unix a YYYY-MM-DD."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit():
        ts = float(value)
        if ts > 1e11:  # milisegundos
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    if text[:4].isdigit():
        return text[:10]
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _join(values) -> str:
    if isinstance(values, str):
        return values
    return ", ".join(str(v) for v in values or [] if v)


def _job(source, **kw) -> Job:
    kw["title"] = html_to_text(kw.get("title", ""))
    kw["description"] = html_to_text(kw.get("description", ""))
    job = Job(source=source, **kw)
    job.remote = True
    job.enriched = True  # la API ya trae la descripción completa
    return job


# --- parsers (uno por portal) -------------------------------------------------
def parse_remotive(payload, name="remotive") -> list:
    return [_job(name, title=i.get("title", ""), url=i.get("url", ""), company=i.get("company_name", ""),
                 location=i.get("candidate_required_location", ""), description=i.get("description", ""),
                 published=_iso(i.get("publication_date")))
            for i in payload.get("jobs", [])]


def parse_remoteok(payload, name="remoteok") -> list:
    jobs = []
    for i in payload:
        if not isinstance(i, dict) or not i.get("position"):
            continue  # el primer elemento es el aviso legal
        desc = f"{i.get('description', '')} {' '.join(i.get('tags') or [])}"
        jobs.append(_job(name, title=i.get("position", ""), url=i.get("url", ""), company=i.get("company", ""),
                         location=i.get("location", ""), description=desc,
                         published=_iso(i.get("date") or i.get("epoch"))))
    return jobs


def parse_jobicy(payload, name="jobicy") -> list:
    return [_job(name, title=i.get("jobTitle", ""), url=i.get("url", ""), company=i.get("companyName", ""),
                 location=_join(i.get("jobGeo")), description=i.get("jobDescription") or i.get("jobExcerpt", ""),
                 published=_iso(i.get("pubDate")))
            for i in payload.get("jobs", [])]


def parse_himalayas(payload, name="himalayas") -> list:
    return [_job(name, title=i.get("title", ""), url=i.get("applicationLink") or i.get("guid", ""),
                 company=i.get("companyName", ""), location=_join(i.get("locationRestrictions")),
                 description=i.get("description") or i.get("excerpt", ""), published=_iso(i.get("pubDate")))
            for i in payload.get("jobs", [])]


def parse_workingnomads(payload, name="workingnomads") -> list:
    return [_job(name, title=i.get("title", ""), url=i.get("url", ""), company=i.get("company_name", ""),
                 location=i.get("location", ""),
                 description=f"{i.get('description', '')} {i.get('tags', '')}",
                 published=_iso(i.get("pub_date")))
            for i in payload]


def parse_getonbrd(payload, name="getonbrd") -> list:
    """Get on Board (LatAm). `remote_modality`: fully_remote (desde cualquier
    país), remote_local (solo desde los países indicados), hybrid, no_remote."""
    jobs = []
    for item in payload.get("data", []):
        a = item.get("attributes", {})
        modality = a.get("remote_modality") or ("fully_remote" if a.get("remote") else "no_remote")
        countries = _join(a.get("countries"))
        if modality == "fully_remote":
            location = "Remoto"
        elif modality == "remote_local":
            location = f"Remoto desde {countries}"
        else:
            location = countries
        company = (a.get("company") or {}).get("data", {}).get("attributes", {}).get("name", "")
        url = (item.get("links") or {}).get("public_url") or a.get("public_url") \
            or f"https://www.getonbrd.com/jobs/{item.get('id', '')}"
        desc = " ".join(a.get(k) or "" for k in ("description", "functions", "desirable"))
        job = _job(name, title=a.get("title", ""), url=url, company=company, location=location,
                   description=desc, published=_iso(a.get("published_at")))
        job.remote = modality in ("fully_remote", "remote_local")
        jobs.append(job)
    return jobs


def parse_rss(xml_text: str, name="weworkremotely") -> list:
    """RSS de We Work Remotely: título "Empresa: Cargo" y región en <region>."""
    jobs = []
    for item in ET.fromstring(xml_text.encode()).iter("item"):
        title = item.findtext("title", "")
        company, _, position = title.partition(": ")
        if not position:
            company, position = "", title
        jobs.append(_job(name, title=position, url=item.findtext("link", "").strip(), company=company,
                         location=item.findtext("region", ""), description=item.findtext("description", ""),
                         published=_iso(item.findtext("pubDate"))))
    return jobs


# --- fuente ---------------------------------------------------------------------
PORTALES = {
    # nombre: (urls por defecto, parser, ¿usa el término de búsqueda?)
    "remotive": (["https://remotive.com/api/remote-jobs?category=software-dev",
                  "https://remotive.com/api/remote-jobs?category=devops",
                  "https://remotive.com/api/remote-jobs?category=customer-support"], parse_remotive, False),
    "remoteok": (["https://remoteok.com/api"], parse_remoteok, False),
    "jobicy": (["https://jobicy.com/api/v2/remote-jobs?count=100&geo=latam"], parse_jobicy, False),
    "himalayas": (["https://himalayas.app/jobs/api?limit=20&offset=0",
                   "https://himalayas.app/jobs/api?limit=20&offset=20"], parse_himalayas, False),
    "weworkremotely": (["https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
                        "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
                        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
                        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"],
                       parse_rss, False),
    "workingnomads": (["https://www.workingnomads.com/api/exposed_jobs/"], parse_workingnomads, False),
    "getonbrd": (["https://www.getonbrd.com/api/v0/search/jobs?query={q}&per_page=50"],
                 parse_getonbrd, True),
}


class RemoteApiSource:
    def __init__(self, cfg: dict, http):
        self.name = cfg["nombre"]
        portal = cfg.get("portal", self.name)
        if portal not in PORTALES:
            raise ValueError(f"Portal remoto desconocido: {portal!r} (opciones: {', '.join(PORTALES)})")
        default_urls, self.parser, self.uses_query = PORTALES[portal]
        self.urls = cfg.get("urls") or default_urls
        self.interval_hours = cfg.get("cada_horas", 0)
        self.http = http
        self._done = False

    def _fetch(self, url: str) -> list:
        resp = self.http.get(url)
        if self.parser is parse_rss:
            return self.parser(resp.text, self.name)
        return self.parser(resp.json(), self.name)

    def search(self, query: str) -> list:
        if not self.uses_query:
            if self._done:  # sin término de búsqueda: basta una consulta por ejecución
                return []
            self._done = True
        jobs = []
        for url in self.urls:
            jobs += self._fetch(url.format(q=query.replace(" ", "+")) if self.uses_query else url)
        log.info("%s: %d ofertas remotas%s", self.name, len(jobs), f" para {query!r}" if self.uses_query else "")
        return jobs

    def enrich(self, job: Job) -> None:
        job.enriched = True
