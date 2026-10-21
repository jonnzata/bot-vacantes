"""Publicaciones de personas en LinkedIn ("estamos contratando", "#vacante"...).

No inicia sesión ni recorre LinkedIn: usa la API de Brave Search para encontrar
publicaciones PÚBLICAS ya indexadas (BRAVE_API_KEY, plan gratuito en
https://api-dashboard.search.brave.com). Del resultado toma el texto de la
publicación y, como muchas vacantes se publican como un diseño en imagen, lee
el texto de la imagen principal con OCR (Tesseract, español + inglés)."""
import io
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote

import requests

from ..models import Job
from ..text import html_to_text

log = logging.getLogger(__name__)

API_URL = "https://api.search.brave.com/res/v1/web/search"
POST_RE = re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/(?:posts|feed/update)/")
# "Ana Gómez on LinkedIn: #vacante ..." / "... en LinkedIn: ..." / "... | LinkedIn"
_TITLE_NOISE = re.compile(r"^.*?\b(?:on|en) LinkedIn:\s*|\s*\|\s*LinkedIn\s*$", re.IGNORECASE)
MAX_IMAGE_BYTES = 6_000_000
IMAGE_MARK = "[Texto de la imagen]"


def ocr_image(data: bytes) -> str:
    """Texto de una imagen. Devuelve "" si no hay Tesseract instalado."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError:
        return ""
    try:
        img = ImageOps.grayscale(Image.open(io.BytesIO(data)))
        if img.width < 1200:  # las letras pequeñas se leen mejor ampliadas
            factor = 1200 / img.width
            img = img.resize((1200, int(img.height * factor)))
        # Dos lecturas: bloque de texto normal (--psm 6) y texto disperso (--psm 11),
        # típico de los diseños/flyers. Juntas fallan menos letras.
        texts = [pytesseract.image_to_string(img, lang="spa+eng", config=f"--psm {psm}") for psm in (6, 11)]
    except Exception as exc:  # imagen dañada, formato raro, falta el idioma...
        log.debug("OCR falló: %s", exc)
        return ""
    return re.sub(r"\s+", " ", " | ".join(texts)).strip()


def post_date(url: str) -> str:
    """Fecha de publicación (YYYY-MM-DD) a partir del id del enlace: en LinkedIn
    los primeros 41 bits del id ("activity-7123...") son la hora en milisegundos."""
    m = re.search(r"(?:activity|ugcPost|share)[-:](\d{18,20})", url)
    if not m:
        return ""
    ms = int(m.group(1)) >> 22
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _slug_words(url: str) -> str:
    """Palabras del enlace (".../posts/empresa_vacante-sistemas-medellin-activity-71...")
    que suelen traer el cargo, los hashtags y la ciudad que el resumen corta."""
    slug = unquote(url.split("?")[0].rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"-?(?:activity|ugcPost|share)-\d+.*$", "", slug)
    return re.sub(r"[-_]+", " ", slug).strip()


class LinkedInPostsSource:
    def __init__(self, cfg: dict, http):
        self.name = cfg["nombre"]
        self.queries = cfg.get("consultas", [])
        self.freshness = cfg.get("frescura", "pw")  # pd=día, pw=semana, pm=mes
        self.interval_hours = cfg.get("cada_horas", 0)
        self.use_ocr = cfg.get("ocr", True)
        self.key = os.environ.get("BRAVE_API_KEY", "")
        self.http = http
        self._done = False

    def parse(self, payload: dict) -> list:
        jobs = []
        for r in (payload.get("web") or {}).get("results", []):
            url = r.get("url", "")
            if not POST_RE.match(url):
                continue
            title = _TITLE_NOISE.sub("", html_to_text(r.get("title", ""))).strip()
            slug = _slug_words(url)
            # El título de una publicación suele ser genérico ("¡Únete al equipo!"):
            # se le añaden los hashtags/palabras del enlace, que traen el cargo.
            if slug and slug.lower() not in title.lower():
                title = f"{title} · {slug}" if title else slug
            text = " ".join([html_to_text(r.get("description", ""))] +
                            [html_to_text(s) for s in r.get("extra_snippets") or []])
            job = Job(title=title[:160] or text[:160], url=url.split("?")[0], source=self.name,
                      description=text, published=post_date(url) or str(r.get("page_age") or "")[:10])
            thumb = r.get("thumbnail") or {}
            job._image = thumb.get("original") or thumb.get("src") or ""
            jobs.append(job)
        return jobs

    def search(self, query: str) -> list:
        # Usa sus propias `consultas` (no los términos generales): una vez por ejecución.
        if self._done:
            return []
        self._done = True
        if not self.key:
            log.info("%s: falta BRAVE_API_KEY; se omite", self.name)
            return []
        jobs = []
        headers = {"X-Subscription-Token": self.key, "Accept": "application/json"}
        for q in self.queries:
            jobs += self.parse(self._query(q, headers))
        log.info("%s: %d publicaciones encontradas", self.name, len(jobs))
        return jobs

    def _query(self, q: str, headers: dict) -> dict:
        # Brave no admite country=CO; el idioma y la fecha sí.
        full = {"q": q, "count": 20, "search_lang": "es", "freshness": self.freshness}
        # Si el plan no acepta algún filtro (error 422), se reintenta solo con lo básico.
        for params in (full, {"q": q, "count": 20}):
            try:
                return self.http.get(API_URL, headers=headers, params=params).json()
            except requests.HTTPError as exc:
                body = exc.response.text[:300] if exc.response is not None else ""
                if exc.response is None or exc.response.status_code != 422 or params is not full:
                    raise RuntimeError(f"Brave respondió {exc}: {body}") from exc
                log.warning("%s: Brave rechazó los filtros (%s); se reintenta sin ellos", self.name, body)
        return {}

    def enrich(self, job: Job) -> None:
        """Añade a la descripción el texto de la imagen de la publicación."""
        image = getattr(job, "_image", "")
        job.enriched = True  # aunque falle la imagen, el texto de la publicación sirve
        if not (self.use_ocr and image):
            return
        try:
            resp = self.http.get(image)
        except Exception as exc:  # enlaces de imagen caducados, 400/403 del CDN...
            log.debug("No se pudo descargar la imagen de %s: %s", job.url, exc)
            return
        if len(resp.content) <= MAX_IMAGE_BYTES:
            text = ocr_image(resp.content)
            if text:
                job.description = f"{job.description}\n{IMAGE_MARK} {text}"
