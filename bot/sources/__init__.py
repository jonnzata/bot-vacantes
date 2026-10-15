from .email_alerts import EmailAlertSource
from .html_listing import HtmlListingSource
from .jooble import JoobleSource


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
        else:
            raise ValueError(f"Tipo de fuente desconocido: {kind!r}")
    return sources
