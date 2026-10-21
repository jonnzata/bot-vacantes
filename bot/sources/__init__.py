from .email_alerts import EmailAlertSource
from .html_listing import HtmlListingSource
from .jooble import JoobleSource
from .remote_apis import RemoteApiSource
from .social_posts import LinkedInPostsSource


def build_sources(config: dict, http) -> list:
    sources = []
    for cfg in config.get("fuentes", []):
        if not cfg.get("activa", True):
            continue
        kind = cfg.get("tipo")
        if kind == "jooble":
            sources.append(JoobleSource(cfg, http))
        elif kind == "correo":
            sources.append(EmailAlertSource(cfg))
        elif kind == "html":
            sources.append(HtmlListingSource(cfg, http))
        elif kind == "remoto":
            sources.append(RemoteApiSource(cfg, http))
        elif kind == "publicaciones":
            sources.append(LinkedInPostsSource(cfg, http))
        else:
            raise ValueError(f"Tipo de fuente desconocido: {kind!r}")
    return sources
