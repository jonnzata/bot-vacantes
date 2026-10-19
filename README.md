# 🔎 Bot de vacantes: sistemas en Antioquia y teletrabajo

Cada hora, el bot busca vacantes en portales de empleo y te las envía por **correo** y/o **WhatsApp**. Solo envía las que cumplen estas condiciones:

- La vacante está en **Antioquia** (Medellín, Valle de Aburrá, Oriente, Urabá…) **o es de teletrabajo** y se puede hacer desde Colombia.
- Es del área de **sistemas / informática** (desarrollo, soporte, redes, infraestructura, cloud, datos, QA…).
- Se ordena según su **coincidencia con tu hoja de vida**: mientras más habilidades de tu HV aparezcan en la vacante, más arriba sale.

Cada vacante incluye el **enlace para postularte** y, si la oferta lo menciona, el **correo** al que debes enviar la HV.

No repite vacantes, porque guarda un registro de las que ya te envió.

## Fuentes

| Fuente | Cómo | Requiere |
|---|---|---|
| **Jooble** | API oficial gratuita. Agrega vacantes de muchos portales colombianos | `JOOBLE_API_KEY` |
| **Computrabajo** | Scraper HTML + datos JobPosting | nada |
| **elempleo.com** | Scraper HTML + datos JobPosting | nada |
| **Magneto** | Scraper HTML + datos JobPosting | nada |
| **Computrabajo / elempleo / Jooble remoto** | Las mismas fuentes, buscando teletrabajo en toda Colombia | nada (Jooble: `JOOBLE_API_KEY`) |
| **Get on Board** | API pública (LatAm, en español) | nada |
| **Remotive, RemoteOK, Jobicy, Himalayas, Working Nomads** | APIs públicas de teletrabajo | nada |
| **We Work Remotely** | RSS público (sysadmin/devops, soporte, programación) | nada |

Las vacantes de **teletrabajo** solo se envían si se pueden hacer desde Colombia: el bot descarta las híbridas o presenciales y las limitadas a otros países ("USA only", "Europe"…). Las regiones aceptadas se ajustan en `ubicacion.regiones_remoto`. Los portales internacionales se consultan cada pocas horas (`cada_horas`) para respetar sus límites de uso.

> LinkedIn e Indeed bloquean los bots y sus términos de uso prohíben el scraping, por eso no se consultan directamente. Muchas de sus vacantes llegan igual a través de Jooble.

Los portales cambian su web de vez en cuando. Si una fuente deja de traer resultados, ajusta su `url` o su `enlace_regex` en `config.yaml`, sin tocar el código. También puedes agregar otros portales de la misma forma.

## Puesta en marcha (gratis, con GitHub Actions)

### 1. Crear las claves

- **Correo (Gmail):** activa la verificación en 2 pasos y luego crea una *contraseña de aplicación* en <https://myaccount.google.com/apppasswords>.
- **WhatsApp (CallMeBot):** desde tu WhatsApp, envía `I allow callmebot to send me messages` al número que indica <https://www.callmebot.com/blog/free-api-whatsapp-messages/>. Te responderán con tu `apikey`.
- **Jooble:** solicita una clave gratuita en <https://jooble.org/api/about>.

### 2. Guardar los secrets en GitHub

Ve a *Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Ejemplo |
|---|---|
| `SMTP_USER` | `tucorreo@gmail.com` |
| `SMTP_PASSWORD` | la contraseña de aplicación (16 letras) |
| `EMAIL_TO` | correo donde recibes las vacantes (opcional; por defecto `SMTP_USER`) |
| `WHATSAPP_PHONE` | `+573001234567` |
| `CALLMEBOT_APIKEY` | la clave que te dio CallMeBot |
| `JOOBLE_API_KEY` | la clave de Jooble |
| `CV_TEXT` | **el texto de tu hoja de vida**: copia el contenido de tu HV y pégalo aquí |

Puedes configurar solo el correo, solo WhatsApp o los dos.

### 3. Activarlo

El código debe quedar en la rama principal (`main`), porque GitHub solo ejecuta desde ahí las tareas programadas. Después, en la pestaña **Actions → Bot de vacantes → Run workflow**, puedes lanzarlo a mano para probarlo.

## Ajustes (`config.yaml`)

- `perfil.busquedas`: los términos que se buscan en los portales.
- `ubicacion.municipios` / `incluir_remoto` / `regiones_remoto`: el filtro de Antioquia y de teletrabajo.
- `area.incluir`: términos claros de sistemas (cuentan en el título o, al menos 2, en la descripción).
- `area.incluir_titulo`: términos ambiguos (`sistemas`, `redes`, `infraestructura`...): solo cuentan en el título y, si hay descripción completa, esta debe confirmar que es de sistemas.
- `area.ignorar`: frases que no son de sistemas ("redes sociales", "sistemas de gestión"...). Si te llega una vacante equivocada, agrega aquí la frase que la coló.
- `area.excluir`: si aparece en el título, la vacante se descarta (ventas, contable, enfermería...).
- `ejecucion.min_puntaje`: súbelo si te llegan vacantes poco relevantes.
- `ejecucion.dias_maximos`, `max_por_ejecucion`, `max_whatsapp`: los límites de cada ejecución.

## Uso local

```bash
pip install -r requirements.txt
cp ~/mi_hv.pdf cv/hoja_de_vida.pdf   # opcional (no se sube a git)
python -m bot.main --dry-run          # muestra las vacantes sin enviar nada
python -m pytest -q                   # pruebas
```
