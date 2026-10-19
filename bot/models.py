import hashlib
import re
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Correos de sistema que aparecen en las páginas y no sirven para postularse.
_IGNORED_EMAIL_PARTS = ("noreply", "no-reply", "example.", "sentry", "wixpress", ".png", ".jpg")


@dataclass
class Job:
    title: str
    url: str
    source: str
    company: str = ""
    location: str = ""
    description: str = ""
    published: str = ""  # fecha ISO (YYYY-MM-DD) si se conoce
    apply_url: str = ""
    emails: list = field(default_factory=list)
    score: int = 0
    matched_skills: list = field(default_factory=list)
    enriched: bool = False
    remote: bool = False  # la fuente garantiza que es teletrabajo
    key: str = ""  # identificador propio cuando la URL no sirve (enlaces de rastreo)

    @property
    def uid(self) -> str:
        key = (self.key or self.url.split("?")[0].split("#")[0] or self.title).lower()
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    def extract_emails(self) -> None:
        found = EMAIL_RE.findall(self.description)
        emails = []
        for e in found:
            e = e.strip(".").lower()
            if any(p in e for p in _IGNORED_EMAIL_PARTS) or e in emails:
                continue
            emails.append(e)
        self.emails = emails

    @property
    def link(self) -> str:
        return self.apply_url or self.url
