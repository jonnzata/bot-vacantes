"""Diagnóstico de fuentes (se lanza a mano desde Actions → Diagnóstico).

Prueba variantes de URL de los portales y resume la estructura de los correos
de alertas, sin imprimir datos personales (de los enlaces solo se muestran el
dominio, la ruta y los NOMBRES de los parámetros)."""
import email
import imaplib
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from bot.http import Http  # noqa: E402
from bot.sources.email_alerts import _html_parts  # noqa: E402

URLS = [
    ("elempleo", r"/co/ofertas-trabajo/[a-z0-9-]+-\d+", [
        "https://www.elempleo.com/co/ofertas-empleo/antioquia/trabajo-sistemas",
        "https://www.elempleo.com/co/ofertas-empleo/medellin/trabajo-sistemas",
        "https://www.elempleo.com/co/ofertas-empleo/trabajo-sistemas/medellin",
        "https://www.elempleo.com/co/ofertas-empleo/trabajo-sistemas",
        "https://www.elempleo.com/co/ofertas-empleo/medellin",
        "https://www.elempleo.com/co/ofertas-empleo/antioquia",
        "https://www.elempleo.com/co/ofertas-empleo/?trabajo=sistemas&ciudad=medellin",
        "https://www.elempleo.com/co/ofertas-empleo/?Trabajo=sistemas&Ciudad=Medellin",
    ]),
    ("computrabajo remoto", r"/ofertas-de-trabajo/oferta-de-trabajo-de-[^\"?#]+", [
        "https://co.computrabajo.com/trabajo-de-sistemas-remoto",
        "https://co.computrabajo.com/trabajo-de-sistemas?mod=2",
        "https://co.computrabajo.com/trabajo-de-sistemas-en-remoto",
        "https://co.computrabajo.com/trabajo-de-sistemas-teletrabajo",
        "https://co.computrabajo.com/trabajo-de-teletrabajo-sistemas",
    ]),
    ("elempleo remoto", r"/co/ofertas-trabajo/[a-z0-9-]+-\d+", [
        "https://www.elempleo.com/co/ofertas-empleo/trabajo-sistemas-remoto",
        "https://www.elempleo.com/co/ofertas-empleo/teletrabajo/trabajo-sistemas",
        "https://www.elempleo.com/co/ofertas-empleo/trabajo-sistemas?modalidad=teletrabajo",
    ]),
    ("magneto", r"/co/empleos/[^\"?#]+", [
        "https://www.magneto365.com/co/trabajos/ofertas-empleo-sistemas-en-antioquia",
        "https://www.magneto365.com/co/trabajos/ofertas-empleo-en-medellin",
        "https://www.magneto365.com/co/trabajos/ofertas-empleo-sistemas",
        "https://www.magneto365.com/co/empleos",
        "https://www.magneto365.com/co/empleos?q=sistemas",
        "https://www.magneto365.com/co/trabajos/ofertas-empleo-remoto",
        "https://www.magneto365.com/co/trabajos/ofertas-empleo-teletrabajo",
    ]),
]


def probar_urls():
    http = Http(pause=1.0)
    for nombre, patron, urls in URLS:
        print(f"\n=== {nombre} ===")
        for url in urls:
            try:
                r = http.session.get(url, timeout=25)
            except Exception as exc:
                print(f"ERR  {url} -> {exc}")
                continue
            html = r.text
            enlaces = sorted(set(re.findall(patron, html)))
            texto = html.lower()
            ant = texto.count("antioquia") + texto.count("medell")
            bog = texto.count("bogot")
            print(f"{r.status_code}  {url}\n     ofertas={len(enlaces)} antioquia/medellin={ant} bogota={bog} "
                  f"jsonld={'JobPosting' in html} ejemplo={enlaces[:3]}")


def probar_remotos():
    """Consulta cada portal de teletrabajo una vez y muestra cuántas vacantes
    pasarían los filtros (con ejemplos de título y región)."""
    import yaml
    from bot.filters import JobFilter
    from bot.sources.remote_apis import RemoteApiSource

    config = yaml.safe_load((Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
    flt = JobFilter(config, [])
    http = Http(pause=1.0)
    for cfg in config["fuentes"]:
        if cfg.get("tipo") != "remoto":
            continue
        print(f"\n=== {cfg['nombre']} ===")
        try:
            jobs = RemoteApiSource(cfg, http).search("soporte")
        except Exception as exc:
            print(f"ERR  {exc!r}")
            continue
        motivos = {}
        for j in jobs:
            r = flt.reject_reason(j) or "ACEPTADA"
            motivos[r] = motivos.get(r, 0) + 1
        print(f"vacantes={len(jobs)} {motivos}")
        for j in jobs[:3]:
            print(f"  ej: {j.title[:60]!r} | {j.location[:40]!r} | {j.published} | desc={len(j.description)}")
        for j in [j for j in jobs if flt.accept(j)][:5]:
            print(f"  OK: {j.title[:60]!r} | {j.location[:40]!r} | {j.url[:70]}")


def resumir_correos():
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")
    if not (user and pwd):
        print("\n(sin SMTP_USER/SMTP_PASSWORD: no se revisan correos)")
        return
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(user, pwd)
        imap.select("INBOX", readonly=True)
        for remitente in ("jobalert.indeed.com", "alert@indeed.com", "jobalerts-noreply@linkedin.com",
                          "magneto365.com"):
            _, data = imap.search(None, "FROM", f'"{remitente}"')
            ids = data[0].split() if data and data[0] else []
            print(f"\n=== correos de {remitente}: {len(ids)} ===")
            if not ids:
                continue
            _, msg_data = imap.fetch(ids[-1], "(BODY.PEEK[])")
            raw = next((p[1] for p in msg_data if isinstance(p, tuple)), b"")
            msg = email.message_from_bytes(raw)
            for html in _html_parts(msg)[:1]:
                soup = BeautifulSoup(html, "html.parser")
                vistos = set()
                for a in soup.find_all("a", href=True):
                    u = urlparse(a["href"].replace("&amp;", "&"))
                    if "/in/" in u.path:  # enlaces a perfiles personales: se omiten
                        continue
                    patron = f"{u.netloc}{re.sub(r'[0-9a-f]{8,}|\\d{5,}', '<id>', u.path)}"
                    claves = ",".join(sorted(parse_qs(u.query)))
                    # Solo se muestra el texto de enlaces a vacantes (no nombres, perfiles, etc.).
                    es_vacante = re.search(r"jobs/view|viewjob|rc/clk|pagead/clk|/empleos?/", u.path)
                    texto = a.get_text(" ", strip=True)[:45] if es_vacante else ""
                    fila = (patron, claves, texto)
                    if fila in vistos:
                        continue
                    vistos.add(fila)
                    print(f"  {patron} ?[{claves}] '{texto}'")
                    if len(vistos) >= 40:
                        break


if __name__ == "__main__":
    probar_remotos()
    probar_urls()
    resumir_correos()
