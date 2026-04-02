# mt-butterfly — Revision y plan de mejora

## 1. Seguridad

### 1.1 Token en query string

**Problema:** El token de autenticacion viaja en la URL (`?t=TOKEN`). Esto significa que:
- Queda en logs de acceso del servidor y proxies intermedios
- Queda en el historial del navegador
- Queda visible en la barra de direccion si alguien ve tu pantalla
- Los WebSockets tampoco soportan headers custom nativamente, pero hay alternativas

**Propuesta:**
- Para las llamadas REST: mover el token a un header `Authorization: Bearer <token>` o a una cookie `HttpOnly`.
- Para WebSockets: enviar el token en el primer mensaje tras la conexion (handshake propio), no en la query string.
- La pagina HTML inicial puede seguir recibiendose con `?t=` pero inmediatamente guardar el token en `sessionStorage` y redirigir a la URL limpia (sin `?t=`). Todas las peticiones posteriores lo envian por header.

### 1.2 Credenciales Gmail en .env del workspace

**Problema:** `tasks.py:_ensure_workspace()` escribe `GMAIL_USER` y `GMAIL_APP_PASSWORD` en texto plano en cada directorio de workspace (`{workspace}/.env`). Cada tarea tiene una copia de tus credenciales tirada en disco.

**Propuesta:**
- Eliminar esa escritura de `.env` por workspace.
- Las tools CLI (`mt-butterfly-gmail`) ya importan `app.config.settings`, que lee del `.env` global de Application Support. No necesitan un `.env` local.
- Si el CLI se ejecuta como subproceso de opencode y no tiene acceso al contexto de la app, pasar las credenciales como variables de entorno del subproceso (en el `env=` del `subprocess_exec`) en vez de escribirlas a disco.

### 1.3 Token por defecto "dev-token"

**Problema:** `config.py` define `auth_token: str = "dev-token"`. Si alguien despliega sin configurar, el servicio arranca accesible con un token conocido publicamente.

**Propuesta:**
- Eliminar el default. Si no hay token configurado, no arrancar el servidor. El wizard ya lo genera, asi que no deberia ser un problema.

---

## 2. Arquitectura del sistema de tareas

### 2.1 El LLM ignora las tools y hace lo que quiere

**Problema principal:** El LLM recibe un prompt con instrucciones de usar `mt-butterfly-gmail` y `mt-butterfly-youtube`, pero nada le impide ignorarlas y escribir sus propios scripts Python. Ya hemos visto que esto pasa (el LLM creo `fetch_news.py` y `send_email.py` con `smtplib` hardcodeado).

Las restricciones por prompt que hemos anadido ("Do NOT write Python scripts") ayudan pero no son una garantia.

**Propuesta — verificacion post-ejecucion:**
- Tras ejecutar la tarea, parsear el output JSONL buscando eventos `tool_use` de tipo bash/shell.
- Verificar que los comandos ejecutados incluyen las tools esperadas (`mt-butterfly-gmail`, `mt-butterfly-youtube`).
- Si detecta que ha escrito ficheros `.py` o ha usado `pip install`, marcar la run como `warning` o `needs_review`.
- Esto no previene el problema pero lo hace visible.

**Propuesta — sandboxing real:**
- Configurar opencode para que solo pueda ejecutar comandos de una whitelist.
- Si opencode soporta restriccion de herramientas (similar a como Claude Code permite `allowedTools`), usarlo.
- Si no, considerar ejecutar las tareas en un contenedor Docker con solo las tools instaladas y sin acceso a `pip` o `python` directo.

### 2.2 No hay timeout para las tareas

**Problema:** `_run_task` llama a `stream_opencode` sin timeout. Si opencode se cuelga o el LLM entra en un bucle, la tarea se queda corriendo indefinidamente, ocupando un slot del scheduler.

**Propuesta:**
- Anadir un campo `timeout_minutes` al modelo `Task` (default: 30).
- Envolver la llamada a `stream_opencode` en `asyncio.wait_for(...)`.
- Si se excede, matar el subproceso y marcar la run como `timeout`.

### 2.3 No hay concurrencia controlada

**Problema:** Si tienes 5 tareas programadas a la misma hora, las 5 lanzan subprocesos `opencode` simultaneamente. No hay limite de concurrencia.

**Propuesta:**
- Usar un `asyncio.Semaphore` para limitar a N ejecuciones simultaneas (configurable, default: 2).
- Las tareas que no caben esperan en cola.

### 2.4 El output de las tareas crece sin limite

**Problema:** `TaskRun.output` guarda todo el JSONL raw de cada ejecucion. Con tareas diarias, la DB va a crecer rapido. No hay limpieza automatica.

**Propuesta:**
- Anadir una politica de retencion: borrar `TaskRun` mas antiguos que N dias (configurable, default: 30).
- Ejecutar la limpieza como un job mas del scheduler (ej: una vez al dia a las 3am).
- Opcionalmente comprimir el output viejo (gzip) o moverlo a fichero.

---

## 3. Diseno del chat

### 3.1 Un solo WebSocket por canal, sin soporte multi-dispositivo

**Problema:** Si abres mt-butterfly en dos pestanas/dispositivos, ambas se conectan al mismo canal pero no se sincronizan. Los mensajes enviados desde una pestana no aparecen en la otra.

**Propuesta:**
- Mantener un registro de conexiones activas por canal.
- Cuando llega un mensaje (user o assistant), broadcast a todas las conexiones de ese canal.
- Sencillo con un `dict[channel_id, set[WebSocket]]`.

### 3.2 El historial se envia completo cada vez que conectas

**Problema:** `ws_chat` envia todos los mensajes del canal al conectar. Si un canal tiene miles de mensajes, la conexion inicial sera lenta.

**Propuesta:**
- Enviar solo los ultimos N mensajes (ej: 50).
- Implementar scroll-back: cuando el usuario hace scroll hacia arriba, pedir mas mensajes via REST (`GET /api/channels/{id}/messages?before={id}&limit=50`).

### 3.3 No hay forma de parar una respuesta en curso

**Problema:** Una vez que opencode empieza a generar una respuesta, no hay forma de cancelarla desde el frontend. Si el LLM se va por las ramas, tienes que esperar.

**Propuesta:**
- Anadir un boton "Stop" en el frontend que envie un mensaje `{"type": "cancel"}` por WebSocket.
- En el backend, matar el subproceso de opencode (`proc.kill()`).
- Guardar la respuesta parcial como mensaje.

---

## 4. CLI y configuracion

### 4.1 Hardcoded a macOS

**Problema:** `~/Library/Application Support/` es especifico de macOS. El proyecto no funciona en Linux ni Windows sin modificar el codigo.

**Propuesta:**
- Usar `platformdirs` (o `appdirs`) para obtener el directorio de configuracion del usuario de forma portable.
- macOS: `~/Library/Application Support/mt-butterfly/`
- Linux: `~/.config/mt-butterfly/`
- Windows: `%APPDATA%/mt-butterfly/`

### 4.2 pytest y pytest-asyncio en dependencies principales

**Problema:** `pyproject.toml` incluye `pytest` y `pytest-asyncio` como dependencias de produccion. Cuando un usuario instala con `uv tool install`, se instalan tambien los frameworks de test.

**Propuesta:**
- Moverlos exclusivamente a `[project.optional-dependencies] dev`.
- Quitar `pytest==8.3.4`, `pytest-asyncio==0.24.0` y `anyio>=4.7.0` de `dependencies`.

### 4.3 Versiones demasiado pinned

**Problema:** Algunas dependencias estan pinned a version exacta (`fastapi==0.115.5`, `uvicorn==0.32.1`) mientras otras usan `>=`. Esto genera conflictos al instalar y es inconsistente.

**Propuesta:**
- Usar `>=` para todas las dependencias en `pyproject.toml` (minimos compatibles).
- Usar un lockfile (`uv.lock`) para reproducibilidad exacta en desarrollo.

---

## 5. Frontend

### 5.1 Todo en un solo `app.js`

**Problema:** `app.js` tiene 267 lineas con toda la logica de chat Y tareas mezclada. Se distinguen por `if (document.getElementById("channel-list"))`. No hay logica de tareas visible en el JS, lo que sugiere que la pagina de tareas usa otro mecanismo o le falta funcionalidad.

**Propuesta:**
- Separar en modulos: `chat.js`, `tasks.js`, `api.js` (comun).
- Usar ES modules (`import/export`) que los navegadores modernos soportan nativamente.

### 5.2 El renderizado de Markdown es fragil

**Problema:** `renderMarkdown()` usa regex simples encadenados. Esto rompe con:
- Code blocks que contienen asteriscos o backticks
- Listas anidadas
- Links

**Propuesta:**
- Usar una libreria ligera como `marked` o `markdown-it` (se puede servir desde `/static/` o cargar desde CDN).
- O al menos, procesar los code blocks primero y proteger su contenido del resto de transformaciones.

### 5.3 No hay pagina de tareas en el JS

**Problema:** En `app.js` no hay logica para la pagina de tareas (crear, editar, ver runs). El HTML `tasks.html` probablemente tiene scripts inline o la logica esta en otro sitio no visible.

*(Esto puede que ya este resuelto con scripts inline en el template — verificar.)*

---

## 6. Base de datos

### 6.1 Sin migraciones

**Problema:** Se usa `Base.metadata.create_all` que crea tablas si no existen pero **no migra** esquemas existentes. Si anades una columna a un modelo, las bases de datos existentes no se actualizan.

**Propuesta:**
- Integrar Alembic para migraciones de esquema.
- Genera migraciones automaticamente con `alembic revision --autogenerate`.
- Se ejecutan al arrancar (`alembic upgrade head` en el lifespan).

### 6.2 SQLite no escala para concurrencia

**Problema menor:** SQLite funciona bien para un solo usuario, que es el caso de uso actual. Pero si alguna vez necesitas multiples usuarios concurrentes, SQLite con WAL mode tiene limitaciones.

**Propuesta:** No hacer nada ahora. Si el proyecto crece, migrar a PostgreSQL es facil gracias a SQLAlchemy (cambiar solo el connection string). Pero vale la pena tenerlo en cuenta.

---

## 7. Skills — no conectadas al sistema

### 7.1 Las skills son documentacion muerta

**Problema:** Los ficheros `app/skills/send_email.md` y `youtube_transcript.md` documentan el uso de las tools con `python -m app.tools.gmail`, no con el CLI `mt-butterfly-gmail`. Ademas, estan empaquetados en la app pero no hay nada en el codigo que los inyecte a opencode.

**Propuesta:**
- Actualizar las skills para documentar los CLIs reales (`mt-butterfly-gmail`, `mt-butterfly-youtube`).
- Inyectar las skills automaticamente en el prompt del scheduler (leer los `.md` y anadirlos al constrained_prompt).
- O mejor aun: si opencode soporta configuracion de skills (como Claude Code soporta `CLAUDE.md`), colocarlas donde opencode las lea automaticamente.

---

## 8. Testing

### 8.1 Los tests no cubren el flujo real de tareas

**Problema:** `test_tasks.py` testea CRUD y scheduling, pero no testea:
- Que el prompt construido incluye las restricciones correctas
- Que `_ensure_workspace` crea los ficheros esperados
- Que el output de una task run se parsea correctamente en el frontend

**Propuesta:**
- Anadir tests unitarios para la generacion del constrained_prompt.
- Anadir tests de integracion que mockeen opencode y verifiquen que el flujo completo funciona (crear task → run → verificar TaskRun output).

### 8.2 No hay tests del frontend

**Problema:** Todo el JS esta sin tests. Cambios en `app.js` pueden romper el chat o las tareas sin detectarlo.

**Propuesta para mas adelante:** Si el frontend crece, considerar Playwright o Cypress para tests E2E. Ahora mismo, con un solo fichero JS, es mas practico testear manualmente.

---

## 9. Operaciones

### 9.1 No hay health check

**Problema:** El LaunchAgent reinicia el proceso si muere, pero no sabe si el servidor esta "sano" (DB corrupta, scheduler parado, etc.).

**Propuesta:**
- Anadir un endpoint `GET /health` (sin auth) que verifique:
  - DB accesible (un `SELECT 1`)
  - Scheduler corriendo
- El plist puede usar un `WatchPaths` o un script wrapper que haga curl al health check.

### 9.2 No hay rotacion de logs

**Problema:** El LaunchAgent escribe a `~/Library/Logs/mt-butterfly/stdout.log` pero no hay rotacion. El log va a crecer indefinidamente.

**Propuesta:**
- Usar `logging.handlers.RotatingFileHandler` (ej: 10MB, 3 backups).
- O configurar `newsyslog` / `logrotate` a nivel de sistema.

---

## Resumen de prioridades

| Prioridad | Item | Impacto |
|-----------|------|---------|
| **Alta** | 2.1 — LLM ignora las tools | La funcionalidad core no funciona de forma fiable |
| **Alta** | 1.2 — Credenciales en cada workspace | Riesgo de seguridad real |
| **Alta** | 7.1 — Skills desconectadas | Documentacion inutil que confunde |
| **Alta** | 2.2 — Sin timeout en tareas | Puede bloquear el sistema |
| **Media** | 1.1 — Token en query string | Riesgo de exposicion |
| **Media** | 4.2 — Test deps en produccion | Instalacion innecesariamente pesada |
| **Media** | 6.1 — Sin migraciones | Primera vez que cambies el esquema va a romper |
| **Media** | 2.4 — Output crece sin limite | La DB se va a inflar |
| **Media** | 3.3 — No hay cancel de respuesta | Mala UX |
| **Baja** | 4.1 — Hardcoded macOS | Solo si quieres soporte multiplataforma |
| **Baja** | 5.1 — JS monolitico | Mantenibilidad |
| **Baja** | 3.1 — Sin multi-dispositivo | Solo si lo usas desde multiples sitios |
| **Baja** | 9.1 — Sin health check | Operaciones |
