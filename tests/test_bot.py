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


# --- Postulación automática ---------------------------------------------------------
GUEST_HTML = """<section>
<h2 class="top-card-layout__title">Ingeniero de Redes y Seguridad</h2>
<a class="topcard__org-name-link">Acme Redes SAS</a>
<span class="topcard__flavor topcard__flavor--bullet">Medellín, Antioquia, Colombia</span>
<div class="show-more-less-html__markup">Buscamos ingeniero con FortiGate y Zabbix. Trabajo presencial.
Envía tu hoja de vida a talento@acmeredes.co con el Asunto: Ingeniero Redes MDE</div>
</section>"""


class _FakeHttp:
    def __init__(self, html):
        self.html = html

    def get(self, url):
        return type("R", (), {"text": self.html})()


def _postulador(tmp_path, html=GUEST_HTML, **cfg):
    from bot.autopostular import AutoPostulador
    from bot.storage import SeenStore
    config = {"autopostulacion": {**CONFIG["autopostulacion"], "activa": True, **cfg}}
    cv = tmp_path / "hv.pdf"
    cv.write_bytes(b"%PDF-1.4 prueba")
    return AutoPostulador(config, _FakeHttp(html), SeenStore(tmp_path / "seen.json"), cv)


def _fake_sent_folder(already):
    class FakeSent:
        opened = 0

        def __init__(self, *a):
            FakeSent.opened += 1

        def contains(self, addr, days):
            return addr in already

        def close(self):
            pass
    return FakeSent


def _linkedin_job(title="Ingeniero de Redes", desc="Medellín, Antioquia"):
    return Job(title=title, url="https://www.linkedin.com/jobs/view/4011223344/",
               source="alertas_correo (linkedin)", description=desc, enriched=True)


def test_guest_posting_and_subject(tmp_path):
    ap = _postulador(tmp_path)
    job = _linkedin_job()
    assert ap.enrich(job)
    assert job.company == "Acme Redes SAS" and job.location.startswith("Medellín")
    assert ap.clean_emails(job.emails) == ["talento@acmeredes.co"]
    assert ap.subject_for(job) == "Ingeniero Redes MDE"
    assert ap.place_ok(job) is None


def test_place_rules(tmp_path):
    ap = _postulador(tmp_path)
    mk = lambda loc, desc: Job(title="Ingeniero", url="u", source="s", location=loc, description=desc)
    assert ap.place_ok(mk("Bogotá, Colombia", "Trabajo presencial")) == "presencial fuera de Medellín"
    assert ap.place_ok(mk("Medellín, Antioquia", "Modalidad híbrida 3x2")) == "híbrida"
    assert ap.place_ok(mk("Madrid, España", "Puesto 100% remoto")) is None
    assert ap.place_ok(mk("United States", "Fully remote position")) is None


def test_excludes_current_employer(tmp_path):
    ap = _postulador(tmp_path)
    job = Job(title="Ingeniero NOC", url="u", source="s", company="Netmask Latam", description="x")
    assert ap.excluded_company(job, ["rrhh@otra.com"])
    job = Job(title="Ingeniero NOC", url="u", source="s", company="Reclutadora", description="x")
    assert ap.excluded_company(job, ["seleccion@netmask.co"])
    assert not ap.excluded_company(job, ["seleccion@acme.co"])


def test_autopostula_sends_cv_once(tmp_path, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def sendmail(self, frm, to, raw): sent.append((to, raw))

    import bot.autopostular as mod
    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mod, "SentFolder", _fake_sent_folder(set()))
    monkeypatch.setenv("SMTP_USER", "yo@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    ap = _postulador(tmp_path)
    other = Job(title="Dev", url="https://computrabajo.com/x", source="computrabajo", description="a@b.co")
    done = ap.run([_linkedin_job(), other])
    assert len(done) == 1
    assert sent[0][0] == ["talento@acmeredes.co"]
    assert "hv.pdf" in sent[0][1] and "Ingeniero Redes MDE" in sent[0][1]
    assert sent[1][0] == ["yo@gmail.com"]          # resumen para ti
    assert ap.run([_linkedin_job()]) == []          # no se repite
    assert len(sent) == 2


def test_autopostula_skips_netmask_and_no_email(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "yo@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    netmask = GUEST_HTML.replace("Acme Redes SAS", "Netmask")
    assert _postulador(tmp_path, html=netmask).run([_linkedin_job()], dry_run=True) == []
    sin_correo = GUEST_HTML.replace("talento@acmeredes.co", "nuestro portal")
    assert _postulador(tmp_path, html=sin_correo).run([_linkedin_job()], dry_run=True) == []


def test_profile_matches_cv(tmp_path):
    ap = _postulador(tmp_path)
    mk = lambda title, desc: Job(title=title, url="u", source="s", description=desc)
    azure = mk("Administrador(a) de Nube Azure / Windows Server",
               "Administración de Windows Server, Active Directory y DNS, nube Azure, ITIL. "
               "Mínimo 2-3 años de experiencia en administración de sistemas.")
    assert ap.profile_ok(azure) is None
    assert {"azure", "windows server", "active directory", "itil"} <= set(azure.matched_skills)
    assert ap.profile_ok(mk("Desarrollador Python", "Python, Docker, Linux, SQL")) == "cargo fuera de tu perfil"
    assert ap.profile_ok(mk("Cybersecurity IAM Specialist", "Experiencia con SailPoint, firewall, siem")) \
        == "pide sailpoint"
    assert ap.profile_ok(mk("Ingeniero de Redes", "Mínimo 8 años de experiencia con FortiGate, VPN y SD-WAN")) \
        == "pide 8 años de experiencia"
    assert ap.profile_ok(mk("Ingeniero de Soporte", "Atención a usuarios y manejo de impresoras")).startswith(
        "pocas coincidencias")
    english = mk("Network Security Engineer", "We are looking for an engineer with experience in Fortinet firewalls "
                 "and VPN. You will work with our team and the customers, and you will own the network. "
                 "We offer a great team for you and your career with the best experience.")
    assert ap.profile_ok(english) == "oferta en inglés"


def test_required_vs_desirable_certifications(tmp_path):
    ap = _postulador(tmp_path)
    upk = Job(title="Profesional certificado(a) en FORTINET NSE4", url="u", source="s",
              location="Área metropolitana de Medellín",
              description="Requisitos indispensables:\nContar con certificación Fortinet NSE4 vigente.\n"
                          "Envía tu hoja de vida al correo: rrhh@upk.co")
    assert ap.profile_ok(upk) == "pide nse4"
    evertec = Job(title="Cybersecurity Specialist Automation", url="u", source="s",
                  description="Lo que buscamos\nConocimientos de Linux y Windows.\nMonitorear el SIEM y gestionar "
                              "incidentes y vulnerabilidades.\nValoraremos adicionalmente\n"
                              "Certificaciones CISSP, Security+ u otras.")
    assert ap.profile_ok(evertec) is None


class _FakeSMTP:
    sent = []

    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def login(self, *a): pass
    def sendmail(self, frm, to, raw): _FakeSMTP.sent.append(to)


def _smtp_env(monkeypatch, already=()):
    import bot.autopostular as mod
    _FakeSMTP.sent = []
    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(mod, "SentFolder", _fake_sent_folder(set(already)))
    monkeypatch.setenv("SMTP_USER", "yo@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "x")


def test_skips_if_already_in_gmail_sent(tmp_path, monkeypatch):
    _smtp_env(monkeypatch, already={"talento@acmeredes.co"})
    ap = _postulador(tmp_path)
    assert ap.run([_linkedin_job()]) == []
    assert _FakeSMTP.sent == []
    assert ap.already_applied("talento@acmeredes.co")   # queda en la memoria del bot


def test_never_writes_twice_to_same_address(tmp_path, monkeypatch):
    _smtp_env(monkeypatch)
    ap = _postulador(tmp_path)
    first = _linkedin_job()
    second = Job(title="Analista de Redes", url="https://www.linkedin.com/jobs/view/4099999999/",
                 source="alertas_correo (linkedin)", description="Medellín", enriched=True)
    assert len(ap.run([first, second])) == 1     # misma dirección en las dos ofertas
    assert _FakeSMTP.sent[0] == ["talento@acmeredes.co"]
    ap.seen.save()
    from bot.storage import SeenStore
    ap2 = _postulador(tmp_path)
    ap2.seen = SeenStore(tmp_path / "seen.json")  # memoria tras reiniciar
    third = Job(title="Ingeniero NOC", url="https://www.linkedin.com/jobs/view/4088888888/",
                source="alertas_correo (linkedin)", description="Medellín", enriched=True)
    assert ap2.run([third]) == []


def test_no_send_if_sent_folder_unavailable(tmp_path, monkeypatch):
    _smtp_env(monkeypatch)
    import bot.autopostular as mod

    class Broken:
        def __init__(self, *a):
            raise OSError("imap caído")
    monkeypatch.setattr(mod, "SentFolder", Broken)
    assert _postulador(tmp_path).run([_linkedin_job()]) == []
    assert _FakeSMTP.sent == []


def test_sent_folder_finds_localized_name(monkeypatch):
    import bot.autopostular as mod

    class FakeImap:
        def __init__(self, host): self.selected = None
        def login(self, *a): pass
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Enviados"']
        def select(self, name, readonly): self.selected = name; return "OK", [b"3"]
        def search(self, *crit): return "OK", [b"7" if '"rrhh@x.co"' in crit else b""]
        def logout(self): pass
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeImap)
    folder = mod.SentFolder("h", "u", "p")
    assert folder.imap.selected == '"[Gmail]/Enviados"'
    assert folder.contains("rrhh@x.co", 120) and not folder.contains("otro@x.co", 120)
