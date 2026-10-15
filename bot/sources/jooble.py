"""Jooble: agregador de empleo con API REST gratuita.
Clave en https://jooble.org/api/about (variable de entorno JOOBLE_API_KEY)."""
import logging
import os

from ..models import Job
from ..text import html_to_text

log = logging.getLogger(__name__)

API_URL = "https://jooble.org/api/{key}"


class JoobleSource:
    def __init__(self, cfg: dict, http):
        self.name = cfg["nombre"]
        self.locations = cfg.get("ubicaciones", ["Antioquia"])
        self.key = os.environ.get("JOOBLE_API_KEY", "")
        self.http = http

    def parse(self, payload: dict) -> list:
        jobs = []
        for item in payload.get("jobs", []):
            jobs.append(Job(
                title=html_to_text(item.get("title", "")),
                url=item.get("link", ""),
                source=f"{self.name} ({item.get('source', '')})".replace(" ()", ""),
                company=item.get("company", ""),
                location=item.get("location", ""),
                description=html_to_text(item.get("snippet", "")),
                published=str(item.get("updated", ""))[:10],
            ))
        return jobs

    def search(self, query: str) -> list:
        if not self.key:
            raise RuntimeError("falta JOOBLE_API_KEY")
        jobs = []
        for loc in self.locations:
            resp = self.http.post(API_URL.format(key=self.key),
                                  json={"keywords": query, "location": loc})
            jobs += self.parse(resp.json())
        log.info("%s: %d ofertas para %r", self.name, len(jobs), query)
        return jobs

    def enrich(self, job: Job) -> None:
        # El enlace de Jooble redirige al portal original; el snippet basta para filtrar.
        job.enriched = True
