import re
import unicodedata

from bs4 import BeautifulSoup


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y con espacios simples."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    if "<" not in html:
        return html.strip()
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def contains_term(text_norm: str, term: str) -> bool:
    """Busca `term` como palabra/frase completa en un texto ya normalizado."""
    term = normalize(term)
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text_norm) is not None


def matched_terms(text_norm: str, terms) -> list:
    return [t for t in terms if contains_term(text_norm, t)]
