import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from bot.cv import extract_skills
from bot.filters import JobFilter
from bot.models import Job
from bot.notify import job_to_text
from bot.sources.html_listing import HtmlListingSource
from bot.sources.jooble import JoobleSource
from bot.sources.jsonld import parse_job_posting

CONFIG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))


def make_filter(skills=("python", "sql")):
    return JobFilter(CONFIG, list(skills))


def test_accepts_it_job_in_medellin():
    job = Job(title="Desarrollador Python Junior", url="u", source="t",
              location="Medellín, Antioquia", description="Experiencia en SQL y Django")
    assert make_filter().accept(job)
    assert "python" in job.matched_skills and "sql" in job.matched_skills


def test_rejects_outside_antioquia():
    job = Job(title="Desarrollador Python", url="u", source="t", location="Bogotá, D.C.")
    assert not make_filter().accept(job)


def test_rejects_non_it_job():
    job = Job(title="Auxiliar contable", url="u", source="t", location="Envigado",
              description="Manejo de cartera. ¿Esta oferta es para ti?")
    assert not make_filter().accept(job)


def test_rejects_excluded_title():
    job = Job(title="Asesor comercial de tecnología", url="u", source="t", location="Itagüí")
    assert not make_filter().accept(job)


def test_rejects_old_job():
    old = (date.today() - timedelta(days=40)).isoformat()
    job = Job(title="Ingeniero de sistemas", url="u", source="t", location="Rionegro", published=old)
    assert not make_filter().accept(job)


def test_bello_matches_as_town_only_in_location():
    job = Job(title="Soporte técnico", url="u", source="t", location="Bello, Antioquia")
    assert make_filter().accept(job)


def test_extracts_application_email():
    job = Job(title="x", url="u", source="t",
              description="Envía tu HV a Talento.Humano@empresa.com.co. noreply@portal.com")
    job.extract_emails()
    assert job.emails == ["talento.humano@empresa.com.co"]


def test_cv_skills():
    assert extract_skills("Ingeniero con Python, SQL Server, AWS y redes Cisco") == [
        "python", "sql", "sql server", "aws", "cisco", "redes"]


LISTING = """
<html><body>
<article class="box_offer">
  <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-de-trabajo-de-analista-de-sistemas-en-medellin-ABC123#lc">
    Analista de sistemas</a></h2>
  <p>Empresa XYZ S.A.S.</p><p><span>Medellín, Antioquia</span></p>
</article>
<article class="box_offer">
  <h2><a href="/ofertas-de-trabajo/oferta-de-trabajo-de-tecnico-de-redes-en-envigado-DEF456">Técnico de redes</a></h2>
  <p>Otra empresa</p><p>Envigado, Antioquia</p>
</article>
<a href="/empresas/xyz">Ver empresa</a>
</body></html>
"""


def test_html_listing_parses_offer_links():
    src = HtmlListingSource({
        "nombre": "computrabajo", "url": "https://x/{q}",
        "enlace_regex": '/ofertas-de-trabajo/oferta-de-trabajo-de-[^"?#]+',
        "base": "https://co.computrabajo.com",
    }, http=None)
    jobs = src.parse_listing(LISTING)
    assert [j.title for j in jobs] == ["Analista de sistemas", "Técnico de redes"]
    assert jobs[0].url == ("https://co.computrabajo.com/ofertas-de-trabajo/"
                           "oferta-de-trabajo-de-analista-de-sistemas-en-medellin-ABC123")
    assert "Medellín" in jobs[0].description


def test_jsonld_job_posting():
    data = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {
        "@type": "JobPosting", "title": "Ingeniero DevOps",
        "hiringOrganization": {"@type": "Organization", "name": "ACME"},
        "jobLocation": {"address": {"addressLocality": "Sabaneta", "addressRegion": "Antioquia"}},
        "description": "<p>AWS, Docker. Postúlate en rrhh@acme.co</p>", "datePosted": "2026-10-10T08:00:00",
    }]}
    html = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    parsed = parse_job_posting(html)
    assert parsed["title"] == "Ingeniero DevOps"
    assert parsed["company"] == "ACME"
    assert parsed["location"] == "Sabaneta, Antioquia"
    assert parsed["published"] == "2026-10-10"
    assert "rrhh@acme.co" in parsed["description"]


def test_jooble_parse_and_message():
    src = JoobleSource({"nombre": "jooble"}, http=None)
    jobs = src.parse({"jobs": [{
        "title": "<b>Soporte</b> TI", "location": "Medellín, Antioquia", "snippet": "Mesa de ayuda",
        "link": "https://jooble.org/desc/1", "company": "Foo", "source": "elempleo.com",
        "updated": "2026-10-14T00:00:00",
    }]})
    job = jobs[0]
    assert job.title == "Soporte TI" and job.source == "jooble (elempleo.com)"
    text = job_to_text(job)
    assert "https://jooble.org/desc/1" in text and "Medellín" in text


def test_rejects_old_job_with_unpadded_date():
    # elempleo envía fechas sin ceros, p. ej. "2026-8-26"
    old = date.today() - timedelta(days=60)
    job = Job(title="Desarrollador Python", url="u", source="t", location="Medellín",
              published=f"{old.year}-{old.month}-{old.day}")
    assert not make_filter().accept(job)


def test_elempleo_regex_matches_real_links():
    src = next(f for f in CONFIG["fuentes"] if f["nombre"] == "elempleo")
    html = ('<a href="/co/ofertas-trabajo/auxiliar-de-sistemas-1886758163">Auxiliar de sistemas</a>'
            '<a href="https://web.whatsapp.com/send?text=https://www.elempleo.com/co/ofertas-trabajo/'
            'auxiliar-de-sistemas-1886758163"></a>')
    jobs = HtmlListingSource(src, http=None).parse_listing(html)
    assert [j.url for j in jobs] == ["https://www.elempleo.com/co/ofertas-trabajo/auxiliar-de-sistemas-1886758163"]
