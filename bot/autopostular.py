"""Postulación automática: envía tu hoja de vida al correo de contacto de las
vacantes de LinkedIn que cumplen tus reglas.

Flujo (en cada ejecución, después de filtrar las vacantes):
1. Toma las vacantes que llegaron por las alertas de LinkedIn de tu Gmail.
2. Lee la página pública de la oferta para obtener la descripción completa.
3. Si la descripción trae un correo para enviar la HV y la vacante cumple las
   reglas (empresa no excluida, Medellín presencial o teletrabajo), envía un
   correo desde tu cuenta con la HV en PDF adjunta.
4. Al final te manda un resumen con las postulaciones enviadas.

Las reglas se ajustan en `config.yaml` → `autopostulacion`."""
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from pathlib import Path

from bs4 import BeautifulSoup

from .filters import NOT_REMOTE_TERMS, REMOTE_TERMS
from .text import matched_terms, normalize

log = logging.getLogger(__name__)

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
_LINKEDIN_ID = re.compile(r"linkedin\.com/jobs/view/(\d+)")
_SUBJECT_RE = re.compile(r"asunto\s*[:\-–]\s*[\"“']?([^\n\"”']{4,120})", re.I)
# Correos que nunca son de reclutamiento.
_BAD_DOMAINS = ("linkedin.com", "licdn.com", "indeed.com", "computrabajo.com", "elempleo.com")

DEFAULT_BODY = """Buen día, equipo de selección{empresa_de}:

Me permito postularme a la vacante de {cargo}. Adjunto mi hoja de vida.

Soy Ingeniero Informático con más de 5 años de experiencia en infraestructura TI y ciberseguridad: administración de firewalls FortiGate y FortiManager en entornos multisede, monitoreo de redes con Zabbix y SNMP, implementación de SIEM (Wazuh) alineado a ISO 27001, administración multinube (Azure y GCP) y automatización con Python y Docker.

{coincidencias}Quedo atento a la posibilidad de una entrevista.

Cordialmente,

{firma}"""


def linkedin_id(job):
    m = _LINKEDIN_ID.search(job.url)
    return m.group(1) if m else None


def parse_guest_posting(html: str) -> dict:
    """Extrae título, empresa, ubicación y descripción de la página pública."""
    soup = BeautifulSoup(html, "html.parser")

    def text(selector):
        node = soup.select_one(selector)
        return node.get_text(" ", strip=True) if node else ""

    desc_node = soup.select_one(".show-more-less-html__markup, .description__text")
    description = desc_node.get_text("\n", strip=True) if desc_node else ""
    return {
        "title": text(".top-card-layout__title, .topcard__title"),
        "company": text(".topcard__org-name-link, .topcard__flavor a"),
        "location": text(".topcard__flavor--bullet"),
        "description": description,
    }


class AutoPostulador:
    def __init__(self, config: dict, http, seen, cv_path: Path):
        cfg = config.get("autopostulacion", {})
        self.active = cfg.get("activa", False)
        self.sources = [normalize(s) for s in cfg.get("fuentes", ["linkedin"])]
        self.exclude_companies = [normalize(c) for c in cfg.get("excluir_empresas", [])]
        self.onsite_towns = cfg.get("ciudades_presencial", ["medellin"])
        self.allow_hybrid = cfg.get("aceptar_hibrido", False)
        self.max_per_day = cfg.get("max_por_dia", 15)
        self.max_details = cfg.get("max_detalles", 30)
        self.body_tpl = cfg.get("mensaje") or DEFAULT_BODY
        self.http = http
        self.seen = seen
        self.cv_path = cv_path
        self.user = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port = int(os.environ.get("SMTP_PORT", "465"))
        self.report_to = os.environ.get("EMAIL_TO", "") or self.user
        self.sender_name = os.environ.get("NOMBRE_REMITENTE", "")
        self.signature = os.environ.get("FIRMA_CORREO", "").replace("\\n", "\n") or self.sender_name

    # --- reglas -------------------------------------------------------------------
    def applies_to_source(self, job) -> bool:
        return any(s in normalize(job.source) for s in self.sources)

    def excluded_company(self, job, emails) -> bool:
        text = normalize(f"{job.company} {job.title} {job.description[:1500]}")
        domains = " ".join(e.split("@")[-1] for e in emails)
        return any(c in text or c.replace(" ", "") in domains for c in self.exclude_companies)

    def place_ok(self, job):
        """None si cumple; si no, el motivo. Medellín presencial o teletrabajo."""
        head = normalize(f"{job.title} {job.location}")
        desc = normalize(job.description)
        hybrid = matched_terms(f"{head} {desc}", ["hibrido", "hibrida", "hybrid", "modalidad mixta"])
        remote = matched_terms(f"{head} {desc}", REMOTE_TERMS)
        if remote and not hybrid and not matched_terms(head, NOT_REMOTE_TERMS):
            return None  # teletrabajo (Colombia u otro país)
        if hybrid and not self.allow_hybrid:
            return "híbrida"
        where = normalize(job.location) or desc[:400]
        if matched_terms(where, self.onsite_towns):
            return None  # presencial en Medellín
        return "presencial fuera de Medellín"

    # --- datos de la vacante ---------------------------------------------------------
    def enrich(self, job) -> bool:
        jid = linkedin_id(job)
        if not jid:
            return False
        data = parse_guest_posting(self.http.get(GUEST_URL.format(id=jid)).text)
        if not data["description"]:
            return False
        for key in ("title", "company", "location"):
            if data[key]:
                setattr(job, key, data[key])
        job.description = data["description"]
        job.extract_emails()
        return True

    @staticmethod
    def clean_emails(emails) -> list:
        return [e for e in emails if not any(e.endswith(d) for d in _BAD_DOMAINS)][:2]

    def subject_for(self, job) -> str:
        m = _SUBJECT_RE.search(job.description)
        if m:
            return m.group(1).strip(" .")
        return f"Postulación – {job.title}"

    def body_for(self, job) -> str:
        skills = ", ".join(job.matched_skills[:6])
        return self.body_tpl.format(
            cargo=job.title,
            empresa=job.company,
            empresa_de=f" de {job.company}" if job.company else "",
            coincidencias=(f"Mi experiencia coincide con lo que buscan en: {skills}.\n\n" if skills else ""),
            firma=self.signature,
        )

    # --- envío ------------------------------------------------------------------------
    def sent_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(1 for k, v in self.seen.data.items() if k.startswith("postulada:") and v.startswith(today))

    def _smtp(self):
        if self.port == 465:
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=30)
            server.starttls()
        server.login(self.user, self.password)
        return server

    def build_message(self, job, to) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["Subject"] = self.subject_for(job)
        msg["From"] = formataddr((self.sender_name, self.user)) if self.sender_name else self.user
        msg["To"] = ", ".join(to)
        msg["Message-ID"] = make_msgid()
        msg.attach(MIMEText(self.body_for(job), "plain", "utf-8"))
        pdf = MIMEApplication(self.cv_path.read_bytes(), _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename=self.cv_path.name)
        msg.attach(pdf)
        return msg

    def ready(self) -> str:
        if not self.active:
            return "desactivada en config.yaml"
        if not (self.user and self.password):
            return "faltan SMTP_USER / SMTP_PASSWORD"
        if not self.cv_path.exists():
            return f"no está la hoja de vida en PDF ({self.cv_path})"
        return ""

    def run(self, jobs, dry_run=False) -> list:
        problem = self.ready()
        if problem and not dry_run:
            log.info("Postulación automática: %s", problem)
            return []
        candidates = [j for j in jobs if self.applies_to_source(j) and f"postulada:{j.uid}" not in self.seen
                      and f"revisada:{j.uid}" not in self.seen]
        budget = self.max_per_day - self.sent_today()
        if not candidates or budget <= 0:
            log.info("Postulación automática: %d candidatas, cupo del día %d", len(candidates), max(budget, 0))
            return []

        plan, details = [], 0
        for job in candidates:
            if len(plan) >= budget or details >= self.max_details:
                break
            details += 1
            try:
                if not self.enrich(job):
                    continue  # sin descripción: se reintenta en otra ejecución
            except Exception as exc:
                log.warning("No se pudo leer %s: %s", job.url, exc)
                continue
            to = self.clean_emails(job.emails)
            repeated = any(f"postulada_correo:{a}|{normalize(job.title)}" in self.seen for a in to)
            reason = ("sin correo de contacto" if not to else
                      "ya se envió a ese correo" if repeated else
                      "empresa excluida" if self.excluded_company(job, to) else self.place_ok(job))
            if reason:
                log.info("No se postula [%s]: %s | %s", reason, job.title, job.company or "-")
                self.seen.add(f"revisada:{job.uid}")
                continue
            plan.append((job, to))

        if dry_run:
            for job, to in plan:
                print(f"\n📨 {job.title} | {job.company} | {job.location}\n   Para: {', '.join(to)}"
                      f"\n   Asunto: {self.subject_for(job)}")
            return [j for j, _ in plan]

        done = []
        if plan:
            with self._smtp() as server:
                for job, to in plan:
                    try:
                        server.sendmail(self.user, to, self.build_message(job, to).as_string())
                    except smtplib.SMTPException as exc:
                        log.warning("No se envió la HV a %s: %s", to, exc)
                        continue
                    self.seen.add(f"postulada:{job.uid}")
                    for addr in to:
                        self.seen.add(f"postulada_correo:{addr}|{normalize(job.title)}")
                    done.append((job, to))
                    log.info("HV enviada a %s (%s)", ", ".join(to), job.title)
                if done:
                    server.sendmail(self.user, [a.strip() for a in self.report_to.split(",")],
                                    self.summary(done).as_string())
        return [j for j, _ in done]

    def summary(self, done) -> MIMEText:
        lines = [f"Se envió tu hoja de vida a {len(done)} vacante(s) de LinkedIn:\n"]
        for job, to in done:
            lines.append(f"• {job.title} — {job.company or 'empresa no indicada'} ({job.location or '-'})\n"
                         f"  Correo: {', '.join(to)}\n  Oferta: {job.link}\n")
        msg = MIMEText("\n".join(lines), "plain", "utf-8")
        msg["Subject"] = f"📨 {len(done)} postulación(es) automática(s) enviadas"
        msg["From"] = self.user
        msg["To"] = self.report_to
        return msg
