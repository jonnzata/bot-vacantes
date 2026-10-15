"""Lee en tu correo (IMAP) las alertas de empleo que te envían LinkedIn, Indeed,
Magneto, etc., y convierte cada vacante del correo en un Job.

Así se aprovechan portales que no permiten bots, de forma legítima: son correos
que esas plataformas te mandan a ti."""
import email
import imaplib
import logging
import os
import re
from datetime import date, timedelta
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

from ..models import Job
from ..text import normalize

log = logging.getLogger(__name__)

# Textos de botones que no son el título de la vacante.
_GENERIC = {"ver empleo", "view job", "postularse", "postulate", "aplicar", "apply", "ver mas",
            "ver oferta", "solicitud sencilla", "easy apply", "ver todos los empleos", "see all jobs"}


def _card_text(anchor, link_re, ident_of) -> str:
    """Texto del bloque de la vacante: sube por el HTML mientras el bloque no
    contenga enlaces de OTRA vacante (en los correos todo va en tablas anidadas)."""
    own = ident_of(anchor["href"])
    node = anchor
    for _ in range(8):
        parent = node.parent
        if parent is None:
            break
        others = {ident_of(a["href"]) for a in parent.find_all("a", href=True)
                  if link_re.search(a["href"].replace("&amp;", "&"))}
        if others - {own}:
            break
        node = parent
    return node.get_text(" ", strip=True)[:600]


def _html_parts(msg) -> list:
    parts = []
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
    return parts


class EmailAlertSource:
    def __init__(self, cfg: dict):
        self.name = cfg["nombre"]
        self.days = cfg.get("dias", 3)
        self.senders = []
        for s in cfg.get("remitentes", []):
            self.senders.append({
                "name": s["nombre"],
                "from": s["de"],
                "link_re": re.compile(s["enlace_regex"]),
                "id_re": re.compile(s["id_regex"]) if s.get("id_regex") else None,
                "url_id": s.get("url_id", ""),
            })
        self.user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")
        self.host = os.environ.get("IMAP_HOST", "imap.gmail.com")
        self._done = False

    @staticmethod
    def _ident(href: str, sender: dict):
        href = href.replace("&amp;", "&")
        m = sender["link_re"].search(href)
        if not m:
            return None
        if sender["id_re"]:
            idm = sender["id_re"].search(href)
            if idm:
                return idm.group(1)
        return m.group(1) if m.groups() else href.split("#")[0]

    # --- lectura del HTML de una alerta -----------------------------------------
    def parse_alert(self, html: str, sender: dict) -> list:
        soup = BeautifulSoup(html, "html.parser")
        jobs = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].replace("&amp;", "&")
            if not sender["link_re"].search(href):
                continue
            ident = self._ident(href, sender)
            has_id = ident != href.split("#")[0]
            url = sender["url_id"].format(id=ident) if has_id and sender["url_id"] else href
            title = a.get_text(" ", strip=True)
            card = _card_text(a, sender["link_re"], lambda h: self._ident(h, sender))
            key = f"{sender['name']}:{ident}"
            good_title = len(title) >= 4 and normalize(title) not in _GENERIC
            job = jobs.get(key)
            if job is None:
                job = jobs[key] = Job(title=title if good_title else "", url=url, key=key,
                                      source=f"{self.name} ({sender['name']})", description=card)
                job.enriched = True
            elif good_title and not job.title:
                job.title = title
            if len(card) > len(job.description):
                job.description = card
        return [j for j in jobs.values() if j.title]

    # --- IMAP ---------------------------------------------------------------------
    def _fetch(self) -> list:
        since = (date.today() - timedelta(days=self.days)).strftime("%d-%b-%Y")
        jobs = []
        with imaplib.IMAP4_SSL(self.host) as imap:
            imap.login(self.user, self.password)
            imap.select("INBOX", readonly=True)  # no marca los correos como leídos
            for sender in self.senders:
                _, data = imap.search(None, "SINCE", since, "FROM", f'"{sender["from"]}"')
                ids = data[0].split() if data and data[0] else []
                found = 0
                for msg_id in ids[-40:]:
                    _, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
                    raw = next((p[1] for p in msg_data if isinstance(p, tuple)), b"")
                    msg = email.message_from_bytes(raw)
                    subject = str(make_header(decode_header(msg.get("Subject", ""))))
                    for html in _html_parts(msg):
                        parsed = self.parse_alert(html, sender)
                        found += len(parsed)
                        jobs += parsed
                    log.debug("%s: %r", sender["name"], subject)
                log.info("%s: %d correos de %s, %d vacantes", self.name, len(ids), sender["name"], found)
        return jobs

    def search(self, query: str) -> list:
        # Los correos no dependen del término de búsqueda: se leen una sola vez.
        if self._done:
            return []
        self._done = True
        if not (self.user and self.password):
            raise RuntimeError("faltan SMTP_USER/SMTP_PASSWORD para leer el correo")
        return self._fetch()

    def enrich(self, job: Job) -> None:
        job.enriched = True
