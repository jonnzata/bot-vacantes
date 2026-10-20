# 🔎 Bot de vacantes: sistemas en Antioquia y teletrabajo

Cada hora, el bot busca vacantes en portales de empleo y te las envía por **correo** y/o **WhatsApp**. Solo envía las que cumplen estas condiciones:

- La vacante está en **Antioquia** (Medellín, Valle de Aburrá, Oriente, Urabá…) **o es de teletrabajo** y se puede hacer desde Colombia.
- Es del área de **sistemas / informática** (desarrollo, soporte, redes, infraestructura, cloud, datos, QA…).
- **No** es para aprendices, practicantes ni pasantes.
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

## Postulación automática (LinkedIn)

Las alertas a tu correo siguen igual. Además, cuando una vacante llega por las **alertas de LinkedIn** de tu Gmail, el bot lee la oferta pública y, si trae un **correo para enviar la HV**, te postula solo:

- Envía desde tu Gmail un correo con tu **hoja de vida en PDF adjunta**. Si la oferta indica un asunto ("Asunto: …"), lo usa.
- **Solo si la vacante cumple con tu hoja de vida** (`autopostulacion.perfil_hv`): el cargo es de tu área (infraestructura, redes, seguridad, cloud, soporte…), la oferta menciona al menos `min_coincidencias` habilidades de tu HV, no exige requisitos que no tienes (NSE4, CCNP, CISSP, inglés B2/C1…) ni más de `max_anios_experiencia` años. Las certificaciones que solo aparecen como *deseables* no descartan la vacante. Si no cumple, no se envía nada y el log dice por qué.
- Solo postula a vacantes **presenciales en Medellín** o de **teletrabajo** (de Colombia o de otro país). Las híbridas se omiten.
- Nunca envía a las empresas de `autopostulacion.excluir_empresas` (por ejemplo, tu empresa actual), ni dos veces a la misma vacante.
- Envía como máximo `max_por_dia` correos al día y al final te manda un **resumen** de las postulaciones.

### Activarla

1. En LinkedIn, crea alertas de empleo (Medellín y "En remoto") para que lleguen a tu Gmail.
2. Cifra tu HV y súbela al repositorio. El repo es público, así que solo se sube cifrada (PowerShell, con Git para Windows):
   ```powershell
   copy C:\ruta\HDVJONNY.pdf cv\hoja_de_vida.pdf
   & "C:\Program Files\Git\usr\bin\gpg.exe" --symmetric --cipher-algo AES256 --output cv/hoja_de_vida.pdf.gpg cv/hoja_de_vida.pdf
   git add cv/hoja_de_vida.pdf.gpg
   git commit -m "HV cifrada"
   git push
   ```
3. Agrega estos secrets:

| Secret | Ejemplo |
|---|---|
| `CV_GPG_PASSPHRASE` | la clave que usaste al cifrar |
| `NOMBRE_REMITENTE` | `Jonny Alberto Zapata Taborda` |
| `FIRMA_CORREO` | `Jonny Alberto Zapata Taborda\nIngeniero Informático\n333 430 6808` (`\n` = salto de línea) |

Para probar sin enviar nada: `python -m bot.main --dry-run` muestra a quién se postularía.

## Ajustes (`config.yaml`)

- `perfil.busquedas`: los términos que se buscan en los portales.
- `ubicacion.municipios` / `incluir_remoto` / `regiones_remoto`: el filtro de Antioquia y de teletrabajo.
- `area.incluir`: términos claros de sistemas (cuentan en el título o, al menos 2, en la descripción).
- `area.incluir_titulo`: términos ambiguos (`sistemas`, `redes`, `infraestructura`...): solo cuentan en el título y, si hay descripción completa, esta debe confirmar que es de sistemas.
- `area.ignorar`: frases que no son de sistemas ("redes sociales", "sistemas de gestión"...). Si te llega una vacante equivocada, agrega aquí la frase que la coló.
- `area.excluir`: si aparece en el título, la vacante se descarta (ventas, contable, enfermería...).
- `area.excluir_descripcion`: si aparece en la descripción, la vacante se descarta ("contrato de aprendizaje", "etapa productiva"...).
- `ejecucion.min_puntaje`: súbelo si te llegan vacantes poco relevantes.
- `ejecucion.dias_maximos`, `max_por_ejecucion`, `max_whatsapp`: los límites de cada ejecución.

## Uso local

```bash
pip install -r requirements.txt
cp ~/mi_hv.pdf cv/hoja_de_vida.pdf   # opcional (no se sube a git)
python -m bot.main --dry-run          # muestra las vacantes sin enviar nada
python -m pytest -q                   # pruebas
```
