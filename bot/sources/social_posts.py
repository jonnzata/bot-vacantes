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
            text = " ".join([html_to_text(r.get("description", ""))] +
                            [html_to_text(s) for s in r.get("extra_snippets") or []])
            job = Job(title=title[:140] or text[:140], url=url.split("?")[0], source=self.name,
                      description=text, published=str(r.get("page_age") or "")[:10])
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
            resp = self.http.get(API_URL, headers=headers, params={
                "q": q, "count": 20, "country": "co", "search_lang": "es", "freshness": self.freshness,
            })
            jobs += self.parse(resp.json())
        log.info("%s: %d publicaciones encontradas", self.name, len(jobs))
        return jobs

    def enrich(self, job: Job) -> None:
        """Añade a la descripción el texto de la imagen de la publicación."""
        image = getattr(job, "_image", "")
        if self.use_ocr and image:
            resp = self.http.get(image)
            if len(resp.content) <= MAX_IMAGE_BYTES:
                text = ocr_image(resp.content)
                if text:
                    job.description = f"{job.description}\n{IMAGE_MARK} {text}"
        job.enriched = True
