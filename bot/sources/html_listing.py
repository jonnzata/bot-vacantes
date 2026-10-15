"""Scraper genérico: descarga la página de resultados de un portal, reconoce los
enlaces a ofertas con una expresión regular y luego lee el detalle de cada
oferta (JSON-LD JobPosting o, en su defecto, el texto de la página)."""
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import Job
from .jsonld import page_fallback, parse_job_posting

log = logging.getLogger(__name__)


def _slug(q: str) -> str:
    return quote(re.sub(r"\s+", "-", q.strip().lower()))


def _card_text(anchor) -> str:
    """Texto de la 'tarjeta' que contiene el enlace (título, empresa, ciudad)."""
    node = anchor
    for _ in range(6):
        if node.parent is None:
            break
        node = node.parent
        if node.name in ("article", "li") or len(node.get_text(" ", strip=True)) > 120:
            break
    return node.get_text(" ", strip=True)[:600]


class HtmlListingSource:
    def __init__(self, cfg: dict, http):
        self.name = cfg["nombre"]
        self.url_tpl = cfg["url"]
        self.link_re = re.compile(cfg["enlace_regex"])
        self.base = cfg.get("base", "")
        self.http = http

    def parse_listing(self, html: str) -> list:
        soup = BeautifulSoup(html, "html.parser")
        jobs, seen = [], set()
        for a in soup.find_all("a", href=True):
            m = self.link_re.search(a["href"])
            if not m:
                continue
            url = urljoin(self.base or a["href"], m.group(0))
            title = a.get_text(" ", strip=True) or a.get("title", "")
            if url in seen or len(title) < 4:
                continue
            seen.add(url)
            jobs.append(Job(title=title, url=url, source=self.name, description=_card_text(a)))
        return jobs

    def search(self, query: str) -> list:
        url = self.url_tpl.format(q=_slug(query))
        resp = self.http.get(url)
        jobs = self.parse_listing(resp.text)
        log.info("%s: %d ofertas para %r", self.name, len(jobs), query)
        return jobs

    def enrich(self, job: Job) -> None:
        html = self.http.get(job.url).text
        data = parse_job_posting(html) or page_fallback(html)
        card = job.description
        for key, val in data.items():
            if val:
                setattr(job, key, val)
        if card and card not in job.description:
            job.description = f"{card}\n{job.description}"
        job.enriched = True
