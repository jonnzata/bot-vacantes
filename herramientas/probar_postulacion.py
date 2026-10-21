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


def main():
    config = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    cv = BASE / config["perfil"].get("hoja_de_vida_pdf", "cv/hoja_de_vida.pdf")
    ap = AutoPostulador(config, http=None, seen=None, cv_path=cv)
    to = [a.strip() for a in ap.report_to.split(",") if a.strip()]
    if not (ap.user and ap.password and to):
        sys.exit("Faltan SMTP_USER / SMTP_PASSWORD")
    if not cv.exists():
        sys.exit(f"No está la hoja de vida en PDF ({cv}): revisa el secret CV_GPG_PASSPHRASE")

    job = Job(title="Ingeniero de Redes y Seguridad", company="Empresa de Ejemplo SAS",
              url="https://www.linkedin.com/jobs/view/0/", source="prueba", location="Medellín, Antioquia",
              description="Administración de FortiGate y firewalls, VPN, redes LAN/WAN, monitoreo con "
                          "Zabbix y SNMP, SIEM Wazuh. Medellín, presencial.")
    reason = ap.profile_ok(job)  # calcula las coincidencias con tu HV como en una vacante real
    msg = ap.build_message(job, to)
    msg.replace_header("Subject", f"[PRUEBA] {msg['Subject']}")
    with ap._smtp() as server:
        server.sendmail(ap.user, to, msg.as_string())
    print(f"Correo de prueba enviado a {', '.join(to)}"
          f" (coincidencias: {', '.join(job.matched_skills) or '-'}; perfil: {reason or 'cumple'})")


if __name__ == "__main__":
    main()
