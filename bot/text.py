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


def _term_re(term: str) -> str:
    return rf"(?<![a-z0-9]){re.escape(normalize(term))}(?![a-z0-9])"


def contains_term(text_norm: str, term: str) -> bool:
    """Busca `term` como palabra/frase completa en un texto ya normalizado."""
    return re.search(_term_re(term), text_norm) is not None


def remove_terms(text_norm: str, terms) -> str:
    """Borra de un texto ya normalizado las frases de `terms` (palabras completas)."""
    for t in terms:
        text_norm = re.sub(_term_re(t), " | ", text_norm)
    return text_norm


def matched_terms(text_norm: str, terms) -> list:
    return [t for t in terms if contains_term(text_norm, t)]
