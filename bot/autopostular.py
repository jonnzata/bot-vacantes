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
import imaplib
import logging
import os
import re
import smtplib
from datetime import date, datetime, timedelta, timezone
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


_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:anos|years?)\b(?:\s+o\s+mas)?\s+(?:de\s+|of\s+)?(?:experiencia|experience)")
_EN_WORDS = {"the", "and", "with", "you", "your", "our", "will", "for", "experience", "team", "we", "are"}
_ES_WORDS = {"el", "la", "los", "las", "con", "para", "del", "experiencia", "equipo", "que", "una", "por"}


def _years_required(desc_norm: str) -> int:
    """Mayor número de años de experiencia que pide la oferta (0 si no dice)."""
    return max((int(n) for n in _YEARS_RE.findall(desc_norm)), default=0)


def _mostly_english(desc_norm: str) -> bool:
    words = re.findall(r"[a-z]+", desc_norm)
    en = sum(w in _EN_WORDS for w in words)
    es = sum(w in _ES_WORDS for w in words)
    return en >= 8 and en > 2 * es


_NICE_TO_HAVE = ["deseable", "deseables", "valoramos", "valoraremos", "se valora", "plus", "un plus", "preferible",
                 "nice to have", "desirable", "is an asset", "bonus", "no excluyente", "opcional"]
_MUST_HEADERS = ["requisitos", "requerimos", "buscamos", "lo que buscamos", "perfil", "obligatorio", "indispensable",
                 "excluyente", "requirements", "qualifications", "must have"]


def _required_terms(description: str, terms) -> list:
    """Términos de `terms` que la oferta pide como REQUISITO. Si solo aparecen
    como deseables ("valoraremos", "deseable", "plus"...), no cuentan."""
    found, nice = [], False
    for raw in description.splitlines():
        line = normalize(raw)
        if not line:
            continue
        hits = matched_terms(line, terms)
        if matched_terms(line, _NICE_TO_HAVE):
            nice = True  # esta línea y su bloque son deseables
            if hits:
                continue
        elif matched_terms(line, _MUST_HEADERS) and not hits:
            nice = False  # empieza un bloque de requisitos
        if hits and not nice:
            found += [h for h in hits if h not in found]
    return found


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
        self.sent_days = cfg.get("revisar_enviados_dias", 120)
        self.imap_host = os.environ.get("IMAP_HOST", "imap.gmail.com")
        self._sent = None  # SentFolder, se abre la primera vez que se necesita
        hv = cfg.get("perfil_hv", {})
        self.roles = hv.get("cargos", [])
        self.excluded_roles = hv.get("cargos_excluidos", [])
        self.cv_skills = hv.get("habilidades", [])
        self.min_matches = hv.get("min_coincidencias", 3)
        self.missing_reqs = hv.get("requisitos_que_no_cumplo", [])
        self.max_years = hv.get("max_anios_experiencia", 0)
        self.skip_english = hv.get("omitir_ofertas_en_ingles", False)
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

    def profile_ok(self, job):
        """None si la vacante encaja con tu HV; si no, el motivo. Guarda en
        job.matched_skills las habilidades de tu HV que pide la oferta."""
        title = normalize(job.title)
        desc = normalize(job.description)
        if self.excluded_roles and matched_terms(title, self.excluded_roles):
            return "cargo fuera de tu perfil"
        if self.roles and not matched_terms(title, self.roles):
            return "cargo fuera de tu perfil"
        if self.skip_english and _mostly_english(desc):
            return "oferta en inglés"
        missing = _required_terms(job.description, self.missing_reqs)
        if missing:
            return f"pide {missing[0]}"
        years = _years_required(desc)
        if self.max_years and years > self.max_years:
            return f"pide {years} años de experiencia"
        job.matched_skills = matched_terms(f"{title} {desc}", self.cv_skills)
        if len(job.matched_skills) < self.min_matches:
            return f"pocas coincidencias con tu HV ({len(job.matched_skills)})"
        return None

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
    def vacancy_key(job) -> str:
        """Huella de la vacante (empresa + cargo), para no postularse dos veces a la
        misma oferta aunque se republique con otro id o con otro correo de contacto.
        Sin empresa no se calcula: el mismo cargo en otra empresa es otra vacante."""
        company = re.sub(r"[^a-z0-9 ]+", " ", normalize(job.company))
        company = re.sub(r"\b(s ?a ?s|s ?a|ltda|inc|llc|colombia)\b", " ", company)
        title = re.sub(r"[^a-z0-9 ]+", " ", normalize(job.title))
        company, title = " ".join(company.split()), " ".join(title.split())
        return f"postulada_vacante:{company}|{title}" if company and title else ""

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
            planned = {a for _, addrs in plan for a in addrs}
            repeated = any(self.already_applied(a) or a in planned for a in to)
            key = self.vacancy_key(job)
            same_vacancy = key and (key in self.seen or key in {self.vacancy_key(j) for j, _ in plan})
            reason = ("sin correo de contacto" if not to else
                      "ya te postulaste a esta vacante" if same_vacancy else
                      "ya se envió a ese correo" if repeated else
                      "empresa excluida" if self.excluded_company(job, to) else
                      self.place_ok(job) or self.profile_ok(job))
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

        # Segunda memoria: tu carpeta de Enviados de Gmail (no se pierde aunque
        # GitHub borre el caché). Si no se puede revisar, no se envía nada.
        if plan:
            try:
                plan = [(job, to) for job, to in plan if not self._in_sent_folder(job, to)]
            except Exception as exc:
                log.error("No se pudo revisar Enviados en Gmail (%s): no se envía nada en esta ejecución", exc)
                return []
            finally:
                self._close_sent()

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
                    if self.vacancy_key(job):
                        self.seen.add(self.vacancy_key(job))
                    for addr in to:
                        self.seen.add(f"postulada_correo:{addr}")
                    done.append((job, to))
                    log.info("HV enviada a %s (%s)", ", ".join(to), job.title)
                if done:
                    server.sendmail(self.user, [a.strip() for a in self.report_to.split(",")],
                                    self.summary(done).as_string())
        return [j for j, _ in done]

    # --- memoria: ¿ya se le escribió a ese correo? -------------------------------------
    def already_applied(self, addr: str) -> bool:
        """Registro del bot (caché de GitHub Actions)."""
        return f"postulada_correo:{addr}" in self.seen

    def _in_sent_folder(self, job, to) -> bool:
        if job.company and self._sent_folder().contains_vacancy(self.subject_for(job), job.company, self.sent_days):
            log.info("No se postula [ya enviaste esa vacante, ver Enviados]: %s | %s", job.title, job.company)
            if self.vacancy_key(job):
                self.seen.add(self.vacancy_key(job))
            self.seen.add(f"revisada:{job.uid}")
            return True
        for addr in to:
            if self._sent_folder().contains(addr, self.sent_days):
                log.info("No se postula [ya le escribiste a %s, ver Enviados]: %s", addr, job.title)
                self.seen.add(f"postulada_correo:{addr}")  # se recuerda para no volver a buscarlo
                self.seen.add(f"revisada:{job.uid}")
                return True
        return False

    def _sent_folder(self):
        if self._sent is None:
            self._sent = SentFolder(self.imap_host, self.user, self.password)
        return self._sent

    def _close_sent(self):
        if self._sent is not None:
            self._sent.close()
            self._sent = None

    def summary(self, done) -> MIMEText:
        lines = [f"Se envió tu hoja de vida a {len(done)} vacante(s) de LinkedIn:\n"]
        for job, to in done:
            lines.append(f"• {job.title} — {job.company or 'empresa no indicada'} ({job.location or '-'})\n"
                         f"  Coincide con tu HV: {', '.join(job.matched_skills[:10])}\n"
                         f"  Correo: {', '.join(to)}\n  Oferta: {job.link}\n")
        msg = MIMEText("\n".join(lines), "plain", "utf-8")
        msg["Subject"] = f"📨 {len(done)} postulación(es) automática(s) enviadas"
        msg["From"] = self.user
        msg["To"] = self.report_to
        return msg


class SentFolder:
    """Carpeta de Enviados de Gmail (IMAP, solo lectura). Gmail la nombra según
    el idioma ("[Gmail]/Enviados", "[Gmail]/Sent Mail"), por eso se busca por
    su marca \\Sent."""

    def __init__(self, host, user, password):
        self.imap = imaplib.IMAP4_SSL(host)
        self.imap.login(user, password)
        folder = self._find_sent()
        status, _ = self.imap.select(f'"{folder}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"no se pudo abrir {folder}")

    def _find_sent(self) -> str:
        _, folders = self.imap.list()
        for raw in folders or []:
            line = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
            if "\\Sent" in line:
                return line.rsplit(' "/" ', 1)[-1].strip().strip('"')
        raise RuntimeError("no se encontró la carpeta de Enviados")

    def contains(self, addr: str, days: int) -> bool:
        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self.imap.search(None, "SINCE", since, "TO", f'"{addr}"')
        if status != "OK":
            raise RuntimeError(f"búsqueda en Enviados falló para {addr}")
        return bool(data and data[0].split())

    def contains_vacancy(self, subject: str, company: str, days: int) -> bool:
        """¿Hay un correo enviado con ese asunto que mencione a la empresa?"""
        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        self.imap.literal = subject.encode("utf-8")  # el asunto puede tener tildes
        status, data = self.imap.search("UTF-8", "SINCE", since, "SUBJECT")
        if status != "OK":
            raise RuntimeError("búsqueda por asunto en Enviados falló")
        ids = data[0].split() if data and data[0] else []
        wanted = normalize(company)
        for msg_id in ids[-20:]:
            _, md = self.imap.fetch(msg_id, "(BODY.PEEK[TEXT]<0.4000>)")
            body = b" ".join(p[1] for p in md if isinstance(p, tuple)).decode("utf-8", errors="ignore")
            if wanted and wanted in normalize(body):
                return True
        return False

    def close(self):
        try:
            self.imap.logout()
        except Exception:
            pass
