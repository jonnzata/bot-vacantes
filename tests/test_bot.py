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


def test_interleave_alternates_sources():
    from bot.main import interleave
    jobs = ["a1", "a2", "a3", "b1"]
    assert interleave(jobs, key=lambda j: j[0]) == ["a1", "b1", "a2", "a3"]


LINKEDIN_ALERT = """
<table><tr><td>
  <a href="https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc&amp;refId=x"><img src="logo.png"></a>
  <table><tr><td>
    <a href="https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc">Ingeniero de Soporte TI</a>
    <p>ACME S.A.S · Medellín, Antioquia, Colombia</p>
  </td></tr></table>
</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099887766/?t=1">Analista de Redes</a>
  <p>Otra Empresa · Bogotá, Distrito Capital, Colombia</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search?keywords=sistemas">Ver todos los empleos</a></td></tr>
</table>
"""


def _email_source():
    from bot.sources.email_alerts import EmailAlertSource
    cfg = next(f for f in CONFIG["fuentes"] if f["tipo"] == "correo")
    return EmailAlertSource(cfg)


def test_linkedin_alert_email():
    src = _email_source()
    jobs = src.parse_alert(LINKEDIN_ALERT, src.senders[0])
    assert [j.title for j in jobs] == ["Ingeniero de Soporte TI", "Analista de Redes"]
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4011223344/"
    flt = make_filter()
    assert flt.accept(jobs[0])        # Medellín
    assert not flt.accept(jobs[1])    # Bogotá


def test_indeed_alert_email_uses_job_key():
    src = _email_source()
    indeed = next(s for s in src.senders if s["name"] == "indeed")
    html = ('<div><a href="https://co.indeed.com/rc/clk/dl?jk=9f8e7d6c5b4a&amp;from=ja">Técnico de sistemas</a>'
            '<p>Datelco - Bello, Antioquia</p></div>'
            '<div><a href="https://co.indeed.com/rc/clk/dl?jk=1234abcd&amp;from=ja">Desarrollador Java</a>'
            '<p>Foo - Envigado, Antioquia</p></div>')
    jobs = src.parse_alert(html, indeed)
    assert [j.url for j in jobs] == ["https://co.indeed.com/viewjob?jk=9f8e7d6c5b4a",
                                     "https://co.indeed.com/viewjob?jk=1234abcd"]
    assert jobs[0].uid != jobs[1].uid


def _area_job(title, description=""):
    return Job(title=title, url="u", source="t", location="Medellín, Antioquia", description=description)


def test_rejects_non_it_jobs_with_ambiguous_words():
    flt = make_filter(skills=("excel", "sql", "redes", "sap"))
    for title, desc in [
        ("Auxiliar de sistemas de gestión de calidad", "Apoyo al sistema integrado de gestión ISO 9001"),
        ("Community Manager - Redes sociales", "Gestión de redes sociales"),
        ("Ingeniero civil de infraestructura vial", "Obras de infraestructura"),
        ("Asesor de ventas de tecnología", "Venta de celulares"),
        ("Ejecutivo comercial TIC", "Venta de planes corporativos"),
        ("Inspector QA/QC soldadura", "Control de calidad en obra"),
        ("Auxiliar contable SAP", "Manejo de Excel"),
        ("Profesional en tecnología de alimentos", "Control de calidad en planta"),
        ("Auxiliar administrativo", "Software contable, informática básica y base de datos de clientes"),
    ]:
        assert flt.reject_reason(_area_job(title, desc)) is not None, title


def test_ambiguous_title_needs_it_terms_in_full_description():
    flt = make_filter()
    relleno = "Responsabilidades del cargo y beneficios de la empresa. " * 8
    assert flt.accept(_area_job("Ingeniero de infraestructura", relleno + "Servidores Linux y AWS"))
    assert not flt.accept(_area_job("Ingeniero de infraestructura", relleno + "Obras y redes de acueducto"))
    # Sin descripción completa (tarjeta de listado o de correo) basta el título.
    assert flt.accept(_area_job("Analista de redes"))


def test_it_terms_in_description_only():
    flt = make_filter()
    assert flt.accept(_area_job("Auxiliar III", "Soporte técnico a usuarios, servidores Windows y SQL"))
    assert not flt.accept(_area_job("Auxiliar III", "Atención al cliente y manejo de software contable"))


# --- Teletrabajo -----------------------------------------------------------------
from bot.sources import remote_apis  # noqa: E402

LARGA = "Join our team. We use Linux, AWS, Docker and Python every day. " * 6


def test_remote_api_parsers():
    jobs = remote_apis.parse_remotive({"jobs": [{
        "title": "Senior DevOps Engineer", "url": "https://remotive.com/1", "company_name": "ACME",
        "candidate_required_location": "LATAM", "description": "<p>Kubernetes</p>",
        "publication_date": "2026-10-15T10:00:00"}]})
    assert (jobs[0].title, jobs[0].location, jobs[0].published, jobs[0].remote) == (
        "Senior DevOps Engineer", "LATAM", "2026-10-15", True)

    jobs = remote_apis.parse_remoteok([{"legal": "aviso"}, {
        "position": "IT Support Specialist", "url": "https://remoteok.com/2", "company": "Foo",
        "location": "Worldwide", "description": "Helpdesk", "tags": ["support"], "date": "2026-10-14T00:00:00+00:00"}])
    assert [j.title for j in jobs] == ["IT Support Specialist"] and "support" in jobs[0].description

    jobs = remote_apis.parse_jobicy({"jobs": [{"jobTitle": "SOC Analyst", "url": "u", "companyName": "Sec",
                                               "jobGeo": "LATAM", "jobDescription": "SIEM",
                                               "pubDate": "2026-10-13 08:00:00"}]})
    assert jobs[0].published == "2026-10-13"

    jobs = remote_apis.parse_himalayas({"jobs": [{"title": "Cloud Engineer", "applicationLink": "u",
                                                  "locationRestrictions": ["Colombia", "Mexico"],
                                                  "description": "AWS", "pubDate": 1760400000}]})
    assert jobs[0].location == "Colombia, Mexico" and jobs[0].published.startswith("2025")

    rss = """<rss><channel><item><title>ACME: Linux Systems Administrator</title>
      <region>Anywhere in the World</region><link>https://weworkremotely.com/x</link>
      <pubDate>Tue, 14 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;Linux&lt;/p&gt;</description>
      </item></channel></rss>"""
    job = remote_apis.parse_rss(rss)[0]
    assert (job.company, job.title, job.published) == ("ACME", "Linux Systems Administrator", "2026-10-14")


def test_getonbrd_modalities():
    def item(modality, countries):
        return {"id": "dev-1", "attributes": {"title": "Desarrollador Backend", "remote_modality": modality,
                                              "countries": countries, "description": "Python",
                                              "published_at": 1760400000},
                "links": {"public_url": "https://www.getonbrd.com/jobs/dev-1"}}
    jobs = remote_apis.parse_getonbrd({"data": [item("fully_remote", ["Chile"]),
                                                item("remote_local", ["Chile"]),
                                                item("remote_local", ["Colombia", "Peru"]),
                                                item("hybrid", ["Colombia"])]})
    flt = make_filter()
    assert [flt.remote_ok(j) for j in jobs] == [True, False, True, False]
    assert jobs[0].url == "https://www.getonbrd.com/jobs/dev-1"


def _remote(title, location, description=LARGA):
    job = Job(title=title, url="u", source="t", location=location, description=description)
    job.remote = True
    return job


def test_remote_jobs_must_be_open_to_colombia():
    flt = make_filter()
    assert flt.accept(_remote("Site Reliability Engineer", "Worldwide"))
    assert flt.accept(_remote("Security Engineer", "LATAM"))
    assert flt.accept(_remote("IT Support Specialist", ""))
    assert flt.accept(_remote("Cybersecurity Analyst", "USA, Colombia, Mexico"))
    assert not flt.accept(_remote("Network Engineer", "USA only"))
    assert not flt.accept(_remote("DevOps Engineer", "Europe"))
    assert not flt.accept(_remote("Software Engineer (Hybrid)", "Worldwide"))
    assert not flt.accept(_remote("Sales Development Representative", "Worldwide"))
    assert not flt.accept(_remote("Security Guard", "Worldwide"))


def test_remote_from_colombian_portals():
    flt = make_filter()
    tele = Job(title="Analista de ciberseguridad", url="u", source="t", location="Bogotá, D.C.",
               description="Modalidad teletrabajo. SIEM y pentesting.")
    hibrido = Job(title="Analista de ciberseguridad", url="u", source="t", location="Bogotá, D.C.",
                  description="Modalidad híbrida, 3 días remoto.")
    presencial = Job(title="Soporte técnico", url="u", source="t", location="Cali, Valle")
    assert flt.accept(tele)
    assert not flt.accept(hibrido)
    assert not flt.accept(presencial)


def test_jsonld_telecommute_marks_location():
    data = {"@type": "JobPosting", "title": "Soporte TI", "jobLocationType": "TELECOMMUTE",
            "jobLocation": {"address": {"addressLocality": "Bogotá"}}, "description": "Mesa de ayuda"}
    parsed = parse_job_posting(f'<script type="application/ld+json">{json.dumps(data)}</script>')
    assert parsed["location"] == "Bogotá, Remoto"
    job = Job(title=parsed["title"], url="u", source="t", location=parsed["location"],
              description=parsed["description"])
    assert make_filter().accept(job)


def test_sources_with_interval_are_not_queried_every_hour(tmp_path):
    from bot.main import collect
    from bot.storage import SeenStore

    class Fake:
        name, interval_hours, calls = "fake", 6, 0

        def search(self, q):
            Fake.calls += 1
            return [Job(title="Desarrollador", url=f"https://x/{Fake.calls}", source="fake")]

    seen = SeenStore(tmp_path / "seen.json")
    assert len(collect([Fake()], ["sistemas"], seen)) == 1
    seen.save()
    again = SeenStore(tmp_path / "seen.json")
    assert collect([Fake()], ["sistemas"], again) == [] and Fake.calls == 1


def test_config_builds_all_sources():
    from bot.sources import build_sources
    names = [s.name for s in build_sources(CONFIG, http=None)]
    for n in ("getonbrd", "remotive", "remoteok", "jobicy", "himalayas", "weworkremotely",
              "workingnomads", "jooble_remoto"):
        assert n in names


def test_remote_location_noise_and_english_exclusions():
    flt = make_filter()
    assert flt.accept(_remote("Desarrollador Backend", "Remoto desde Remoto"))
    assert not flt.accept(_remote("Enterprise Customer Success Manager", "Anywhere"))
    assert not flt.accept(_remote("Product Manager, Platform", "Worldwide"))


def test_rejects_apprentices_and_interns():
    flt = make_filter()
    for title in ["Aprendiz técnico en sistemas", "Practicante de ingeniería de sistemas",
                  "Pasante desarrollo de software", "Software Engineering Intern", "Trainee DevOps",
                  "Aprendiz SENA soporte técnico", "Práctica profesional en sistemas"]:
        assert not flt.accept(_area_job(title)), title
    job = _area_job("Auxiliar de sistemas", "Contrato de aprendizaje, etapa productiva. Soporte técnico.")
    assert flt.reject_reason(job) == "aprendiz o practica"
    assert flt.accept(_area_job("Internal IT Support Specialist", "Helpdesk, Active Directory"))


def test_accepts_all_it_jobs_even_without_cv_matches():
    flt = make_filter(skills=())
    relleno = "Responsabilidades del cargo y beneficios de la empresa. " * 8
    # Título ambiguo confirmado con términos de redes en español
    assert flt.accept(_area_job("Analista de redes", relleno + "Configuración de switches, routers y firewall Fortinet"))
    # Sin término en el título: dos términos técnicos en la descripción bastan
    assert flt.accept(_area_job("Profesional II", "Administración de servidores y bases de datos SQL Server"))
    assert flt.accept(_area_job("Técnico informático", ""))
    assert not flt.accept(_area_job("Profesional universitario", relleno + "Servidor público de carrera administrativa"))


def test_linkedin_mailbox_is_optional(monkeypatch):
    from bot.sources.email_alerts import EmailAlertSource
    cfg = next(f for f in CONFIG["fuentes"] if f["nombre"] == "alertas_linkedin")
    monkeypatch.delenv("LINKEDIN_IMAP_USER", raising=False)
    monkeypatch.setenv("SMTP_USER", "bot@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    assert EmailAlertSource(cfg).search("sistemas") == []  # sin secrets: se omite, no falla
    monkeypatch.setenv("LINKEDIN_IMAP_USER", "otro@gmail.com")
    monkeypatch.setenv("LINKEDIN_IMAP_PASSWORD", "y")
    src = EmailAlertSource(cfg)
    assert (src.user, src.password) == ("otro@gmail.com", "y")
    jobs = src.parse_alert(LINKEDIN_ALERT, src.senders[0])
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/4011223344/"


# --- Publicaciones de LinkedIn ---------------------------------------------------
import shutil  # noqa: E402

import pytest  # noqa: E402

from bot.sources.social_posts import LinkedInPostsSource, ocr_image  # noqa: E402

BRAVE = {"web": {"results": [
    {"title": "Ana Gómez en LinkedIn: #vacante #empleo Buscamos Técnico en sistemas",
     "url": "https://www.linkedin.com/posts/ana-gomez_vacante-empleo-activity-7111?utm_source=x",
     "description": "Buscamos <strong>Técnico en sistemas</strong> para Medellín. Soporte técnico a usuarios.",
     "page_age": "2026-10-20T10:00:00", "thumbnail": {"original": "https://media.licdn.com/img.jpg"}},
    {"title": "Ofertas | LinkedIn", "url": "https://www.linkedin.com/jobs/search?keywords=x",
     "description": "listado"},  # no es una publicación
]}}


def _post_source():
    cfg = next(f for f in CONFIG["fuentes"] if f["tipo"] == "publicaciones")
    return LinkedInPostsSource(cfg, http=None)


def test_linkedin_posts_parse():
    jobs = _post_source().parse(BRAVE)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "#vacante #empleo Buscamos Técnico en sistemas · ana gomez vacante empleo"
    assert job.url == "https://www.linkedin.com/posts/ana-gomez_vacante-empleo-activity-7111"
    assert job.published == "2026-10-20" and job._image == "https://media.licdn.com/img.jpg"
    assert make_filter().accept(job)  # Medellín viene en el texto, no en un campo


def test_linkedin_posts_without_key_are_skipped(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert _post_source().search("") == []


def _image_bytes(lines):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 120 * len(lines) + 80), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=64)
    for i, line in enumerate(lines):
        draw.text((40, 40 + 120 * i), line, fill="black", font=font)
    buf = __import__("io").BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract no instalado")
def test_vacancy_published_as_image_is_read_with_ocr():
    png = _image_bytes(["VACANTE", "Analista de soporte TI", "Medellin - presencial", "Envia tu HV a", "rrhh@acme.co"])

    class FakeHttp:
        def get(self, url):
            return type("R", (), {"content": png})()

    src = _post_source()
    src.http = FakeHttp()
    job = Job(title="Juan Pérez: ¡Estamos contratando! 🚀", url="https://www.linkedin.com/posts/x", source="t",
              description="¡Estamos contratando! Postúlate 👇")
    job._image = "https://media.licdn.com/img.png"
    flt = make_filter()
    assert not flt.accept(job)  # sin la imagen no hay datos para saber que es de sistemas
    src.enrich(job)
    job.extract_emails()
    assert "soporte" in job.description.lower()
    assert flt.accept(job)
    assert any(m.endswith("acme.co") for m in job.emails)
    assert "verifícalo" in job_to_text(job)


def test_ocr_without_tesseract_returns_empty(monkeypatch):
    import pytesseract
    def boom(*a, **k):
        raise pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pytesseract, "image_to_string", boom)
    assert ocr_image(_image_bytes(["hola"])) == ""


def test_international_remote_jobs_need_it_title():
    flt = make_filter()
    desc = "We use SQL, Python and AWS daily. Linux servers and Docker. " * 6
    assert not flt.accept(_remote("Risk Analyst", "Worldwide", desc))
    assert not flt.accept(_remote("Customer Support Consultant hospitality", "Worldwide", desc))
    assert not flt.accept(_remote("Norwegian Tech Linguistic Tester", "Anywhere", desc))
    assert flt.accept(_remote("Infrastructure Engineer", "LATAM", desc))
    assert flt.accept(_remote("Senior Backend Engineer", "Worldwide", desc))


def test_brave_retries_without_filters_on_422(monkeypatch):
    import requests

    calls = []

    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._payload, self.text = status, payload, '{"error":"invalid"}'

        def json(self):
            return self._payload

    class FakeHttp:
        def get(self, url, headers=None, params=None):
            calls.append(params)
            if "freshness" in params:
                raise requests.HTTPError("422", response=Resp(422, {}))
            return Resp(200, BRAVE)

    monkeypatch.setenv("BRAVE_API_KEY", "k")
    src = _post_source()
    src.http = FakeHttp()
    src.queries = ["site:linkedin.com/posts vacante sistemas"]
    jobs = src.search("")
    assert len(jobs) == 1 and len(calls) == 2 and "freshness" not in calls[1]
    assert "country" not in calls[0]  # Brave no admite Colombia como país


def test_linkedin_post_uses_url_words_and_survives_bad_image():
    payload = {"web": {"results": [{
        "title": "Empresa XYZ en LinkedIn: ¡Únete a nuestro equipo!",
        "url": "https://co.linkedin.com/posts/empresa-xyz_vacante-ingeniero-de-sistemas-medellin-activity-7123456",
        "description": "¡Únete a nuestro equipo! Postúlate ya.",
        "thumbnail": {"original": "https://media.licdn.com/caducada.jpg"}}]}}
    src = _post_source()
    job = src.parse(payload)[0]
    assert job.title == "¡Únete a nuestro equipo! · empresa xyz vacante ingeniero de sistemas medellin"

    class BrokenHttp:
        def get(self, url):
            raise RuntimeError("400 Bad Request")

    src.http = BrokenHttp()
    src.enrich(job)  # no debe fallar
    assert job.enriched and make_filter().accept(job)


def test_linkedin_post_date_from_activity_id():
    from bot.sources.social_posts import post_date
    # 7123456789012345678 >> 22 = 1698364445927 ms → 26-oct-2023
    assert post_date("https://www.linkedin.com/posts/x_vacante-activity-7123456789012345678-AbCd") == "2023-10-26"
    assert post_date("https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/") == "2023-10-26"
    assert post_date("https://www.linkedin.com/posts/sin-id") == ""
    old = Job(title="Vacante ingeniero de sistemas Medellín", url="u", source="t",
              published=post_date("https://www.linkedin.com/posts/x-activity-7123456789012345678"))
    assert make_filter().reject_reason(old) == "antigua"
