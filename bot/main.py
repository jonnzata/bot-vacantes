"""Bot de vacantes: busca, filtra (Antioquia + sistemas + tu HV) y notifica.

Uso:
    python -m bot.main             # ejecución normal
    python -m bot.main --dry-run   # muestra las vacantes sin enviar ni guardar
"""
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .cv import extract_skills, load_cv_text
from .filters import JobFilter
from .http import Http
from .notify import EmailNotifier, WhatsAppNotifier, job_to_text
from .sources import build_sources
from .storage import SeenStore

BASE_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("job_bot")


def is_due(source, seen) -> bool:
    """Las fuentes con `cada_horas` solo se consultan cada tantas horas."""
    hours = getattr(source, "interval_hours", 0)
    last = seen.last_run(source.name)
    return not (hours and last and datetime.now(timezone.utc) - last < timedelta(hours=hours) - timedelta(minutes=10))


def collect(sources, queries, seen) -> list:
    """Busca en todas las fuentes y devuelve vacantes nuevas sin duplicados."""
    jobs, uids = [], set()
    for source in sources:
        if not is_due(source, seen):
            log.info("%s: se omite en esta ejecución (se consulta cada %s h)", source.name, source.interval_hours)
            continue
        for q in queries:
            try:
                found = source.search(q)
            except Exception as exc:  # una fuente caída no detiene el bot
                log.warning("%s falló con %r: %s", source.name, q, exc)
                break
            if getattr(source, "interval_hours", 0):
                seen.mark_run(source.name)
            for job in found:
                if job.uid in seen or job.uid in uids:
                    continue
                uids.add(job.uid)
                job._source = source
                jobs.append(job)
    return jobs


def interleave(jobs, key) -> list:
    """Alterna las vacantes por fuente (A1, B1, A2, B2, ...) para que ningún
    portal acapare los cupos de detalle ni de envío."""
    groups = {}
    for job in jobs:
        groups.setdefault(key(job), []).append(job)
    result, queues = [], list(groups.values())
    while queues:
        result += [q.pop(0) for q in queues]
        queues = [q for q in queues if q]
    return result


def by_source(job) -> str:
    return job._source.name


def run(config_path: Path, dry_run: bool) -> list:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    run_cfg = config.get("ejecucion", {})
    profile = config.get("perfil", {})

    skills = extract_skills(load_cv_text(profile.get("hoja_de_vida", ""), BASE_DIR))
    log.info("Habilidades detectadas en la HV: %s", ", ".join(skills) or "(ninguna)")

    job_filter = JobFilter(config, skills)
    seen = SeenStore(BASE_DIR / "data" / "seen.json")
    http = Http(pause=run_cfg.get("pausa_segundos", 1.5))
    sources = build_sources(config, http)

    candidates = [j for j in collect(sources, profile.get("busquedas", []), seen) if job_filter.title_ok(j)]
    candidates = interleave(candidates, by_source)
    log.info("%d vacantes nuevas por revisar (%s)", len(candidates), _count(candidates))

    accepted, details, reasons = [], 0, {}
    for job in candidates:
        if not job.enriched and details < run_cfg.get("max_detalles", 60):
            details += 1
            try:
                job._source.enrich(job)
            except Exception as exc:
                log.warning("No se pudo leer el detalle de %s: %s", job.url, exc)
        job.extract_emails()
        reason = job_filter.reject_reason(job)
        if reason is None:
            accepted.append(job)
            continue
        key = f"{by_source(job)}: {reason}"
        reasons[key] = reasons.get(key, 0) + 1
        if reasons[key] <= 2:  # ejemplos en el log para diagnosticar
            log.info("Descartada [%s] %s | %s | %s", key, job.title, job.location or "-", job.published or "-")
        if job.enriched:
            seen.add(job.uid)  # revisada y descartada: no volver a descargarla

    log.info("Descartes: %s", ", ".join(f"{k} = {v}" for k, v in sorted(reasons.items())) or "ninguno")
    log.info("%d vacantes cumplen los filtros (%s)", len(accepted), _count(accepted))
    accepted.sort(key=lambda j: j.score, reverse=True)
    accepted = interleave(accepted, by_source)[: run_cfg.get("max_por_ejecucion", 25)]
    log.info("%d vacantes se envían (%s)", len(accepted), _count(accepted))

    if dry_run:
        for job in accepted:
            print(f"\n[{job.score}] " + job_to_text(job))
        return accepted
    if not accepted:
        seen.save()
        return accepted

    notifiers = [n for n in (EmailNotifier(), WhatsAppNotifier(run_cfg.get("max_whatsapp", 10))) if n.enabled]
    if not notifiers:
        log.error("No hay canal configurado (SMTP_* o WHATSAPP_PHONE/CALLMEBOT_APIKEY)")
        return accepted
    sent = False
    for notifier in notifiers:
        try:
            notifier.send(accepted)
            sent = True
        except Exception as exc:
            log.error("Falló %s: %s", type(notifier).__name__, exc)
    if sent:  # solo se marcan como vistas si llegaron por algún canal
        for job in accepted:
            seen.add(job.uid)
    seen.save()
    return accepted


def _count(jobs) -> str:
    counts = {}
    for job in jobs:
        counts[by_source(job)] = counts.get(by_source(job), 0) + 1
    return ", ".join(f"{k}: {v}" for k, v in counts.items()) or "ninguna"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    run(Path(args.config), args.dry_run)


if __name__ == "__main__":
    main()
