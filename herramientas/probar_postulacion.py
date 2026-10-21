"""Envía a TU correo (EMAIL_TO, o SMTP_USER si no está) un ejemplo del correo de
postulación automática, con la hoja de vida adjunta, tal como lo recibiría una
empresa. Nunca se envía a otra dirección. Se lanza desde Actions → "Probar
correo de postulación"."""
import os
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from bot.autopostular import AutoPostulador  # noqa: E402
from bot.models import Job  # noqa: E402


EJEMPLOS = [
    ("Analista de Ciberseguridad", "Monitoreo en SIEM Wazuh, gestión de vulnerabilidades, hardening, "
                                   "atención de incidentes e ISO 27001."),
    ("Ingeniero de Redes", "Administración de FortiGate y firewalls, VPN, redes LAN/WAN, monitoreo con Zabbix y SNMP."),
    ("Técnico de Soporte TI", "Soporte N2, mesa de servicio en GLPI, ITIL, Active Directory, Windows Server y antivirus."),
    ("Ingeniero de Infraestructura Cloud", "Azure y GCP, servidores Linux, Docker, backup y DRP."),
    ("Analista de Sistemas", "Soporte a usuarios, redes, servidores Windows Server, Active Directory y backup."),
]


def main():
    config = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    cv = BASE / config["perfil"].get("hoja_de_vida_pdf", "cv/hoja_de_vida.pdf")
    ap = AutoPostulador(config, http=None, seen=None, cv_path=cv)
    to = [a.strip() for a in ap.report_to.split(",") if a.strip()]
    if not (ap.user and ap.password and to):
        sys.exit("Faltan SMTP_USER / SMTP_PASSWORD")
    if not cv.exists():
        sys.exit(f"No está la hoja de vida en PDF ({cv}): revisa el secret CV_GPG_PASSPHRASE")

    with ap._smtp() as server:
        for title, desc in EJEMPLOS:  # un correo por cada área (párrafo de experiencia distinto)
            job = Job(title=title, company="Empresa de Ejemplo SAS", url="https://www.linkedin.com/jobs/view/0/",
                      source="prueba", location="Medellín, Antioquia", description=f"{desc} Medellín, presencial.")
            reason = ap.profile_ok(job)  # coincidencias con tu HV, como en una vacante real
            msg = ap.build_message(job, to)
            area = ap.experience_for(job)[0]
            msg.replace_header("Subject", f"[PRUEBA {area}] {msg['Subject']}")
            server.sendmail(ap.user, to, msg.as_string())
            print(f"Prueba [{area}] enviada: {title} (coincidencias: {', '.join(job.matched_skills) or '-'};"
                  f" perfil: {reason or 'cumple'})")


if __name__ == "__main__":
    main()
