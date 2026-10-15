"""Envío de vacantes por correo (SMTP) y WhatsApp (CallMeBot)."""
import html
import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def job_to_text(job) -> str:
    lines = [f"💼 {job.title}"]
    if job.company:
        lines.append(f"🏢 {job.company}")
    if job.location:
        lines.append(f"📍 {job.location}")
    if job.published:
        lines.append(f"📅 {job.published}")
    if job.matched_skills:
        lines.append(f"✅ Coincide con tu HV: {', '.join(job.matched_skills[:8])}")
    lines.append(f"🔗 Postúlate: {job.link}")
    if job.emails:
        lines.append(f"✉️ Enviar HV a: {', '.join(job.emails)}")
    lines.append(f"Fuente: {job.source}")
    return "\n".join(lines)


def job_to_html(job) -> str:
    e = html.escape
    rows = []
    if job.company:
        rows.append(f"🏢 {e(job.company)}")
    if job.location:
        rows.append(f"📍 {e(job.location)}")
    if job.published:
        rows.append(f"📅 Publicada: {e(job.published)}")
    if job.matched_skills:
        rows.append(f"✅ Coincide con tu HV: {e(', '.join(job.matched_skills[:8]))}")
    if job.emails:
        mails = ", ".join(f'<a href="mailto:{e(m)}">{e(m)}</a>' for m in job.emails)
        rows.append(f"✉️ Enviar HV a: {mails}")
    snippet = e(job.description[:350]) + ("…" if len(job.description) > 350 else "")
    return (
        '<div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0">'
        f'<h3 style="margin:0 0 6px">{e(job.title)}</h3>'
        f'<div style="font-size:14px;line-height:1.6">{"<br>".join(rows)}</div>'
        f'<p style="color:#555;font-size:13px">{snippet}</p>'
        f'<a href="{e(job.link)}" style="background:#1a73e8;color:#fff;padding:8px 14px;'
        'border-radius:6px;text-decoration:none">Postularme</a>'
        f'<span style="color:#888;font-size:12px;margin-left:10px">Fuente: {e(job.source)}</span>'
        "</div>"
    )


class EmailNotifier:
    def __init__(self):
        self.user = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.to = os.environ.get("EMAIL_TO", "") or self.user
        self.host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port = int(os.environ.get("SMTP_PORT", "465"))

    @property
    def enabled(self) -> bool:
        return bool(self.user and self.password)

    def send(self, jobs) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔎 {len(jobs)} vacante(s) de sistemas en Antioquia"
        msg["From"] = self.user
        msg["To"] = self.to
        text = "\n\n".join(job_to_text(j) for j in jobs)
        body = "".join(job_to_html(j) for j in jobs)
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(f"<html><body style='font-family:Arial'>{body}</body></html>", "html", "utf-8"))
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as s:
                s.login(self.user, self.password)
                s.sendmail(self.user, [a.strip() for a in self.to.split(",")], msg.as_string())
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                s.starttls()
                s.login(self.user, self.password)
                s.sendmail(self.user, [a.strip() for a in self.to.split(",")], msg.as_string())
        log.info("Correo enviado a %s con %d vacantes", self.to, len(jobs))


class WhatsAppNotifier:
    """CallMeBot: servicio gratuito para enviarte WhatsApp a ti mismo.
    Activación: https://www.callmebot.com/blog/free-api-whatsapp-messages/"""

    URL = "https://api.callmebot.com/whatsapp.php"

    def __init__(self, max_messages: int = 10):
        self.phone = os.environ.get("WHATSAPP_PHONE", "")  # ej: +573001234567
        self.apikey = os.environ.get("CALLMEBOT_APIKEY", "")
        self.max_messages = max_messages

    @property
    def enabled(self) -> bool:
        return bool(self.phone and self.apikey)

    def send(self, jobs) -> None:
        to_send = jobs[: self.max_messages]
        for job in to_send:
            resp = requests.get(self.URL, timeout=30, params={
                "phone": self.phone, "text": job_to_text(job), "apikey": self.apikey,
            })
            resp.raise_for_status()
            time.sleep(3)  # CallMeBot limita la frecuencia de mensajes
        if len(jobs) > len(to_send):
            requests.get(self.URL, timeout=30, params={
                "phone": self.phone, "apikey": self.apikey,
                "text": f"…y {len(jobs) - len(to_send)} vacante(s) más. Revisa tu correo.",
            })
        log.info("WhatsApp: %d mensajes enviados", len(to_send))
