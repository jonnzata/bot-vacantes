"""Lectura de datos schema.org/JobPosting que casi todos los portales incluyen
en sus páginas de detalle (los usa Google for Jobs)."""
import json

from bs4 import BeautifulSoup

from ..text import html_to_text


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _walk(node["@graph"])


def _is_job(node: dict) -> bool:
    t = node.get("@type")
    return t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)


def _location(job: dict) -> str:
    locs = job.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for loc in locs:
        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
        if isinstance(addr, str):
            parts.append(addr)
            continue
        for key in ("addressLocality", "addressRegion"):
            val = addr.get(key)
            if isinstance(val, dict):
                val = val.get("name")
            for v in (val if isinstance(val, list) else [val]):  # Magneto usa listas
                if v and str(v) not in parts:
                    parts.append(str(v))
    if job.get("jobLocationType") == "TELECOMMUTE":
        parts.append("Remoto")
    return ", ".join(parts)


def parse_job_posting(html: str):
    """Devuelve un dict con title, company, location, description, published,
    apply_url o None si la página no tiene JobPosting."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "", strict=False)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            if not _is_job(node):
                continue
            org = node.get("hiringOrganization") or {}
            company = org.get("name", "") if isinstance(org, dict) else str(org)
            return {
                "title": html_to_text(node.get("title", "")),
                "company": company,
                "location": _location(node),
                "description": html_to_text(node.get("description", "")),
                "published": str(node.get("datePosted", ""))[:10],
                "apply_url": node.get("url", "") if isinstance(node.get("url"), str) else "",
            }
    return None


def page_fallback(html: str) -> dict:
    """Si no hay JobPosting, toma el texto visible de la página."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return {"description": main.get_text(" ", strip=True)[:6000]}
