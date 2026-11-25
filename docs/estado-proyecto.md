# Estado del proyecto Guako

Actualizado el 2026-11-24 con la fase de pronunciación (secciones «Pronunciación» y «Estado del MVP»; el resto sigue como el 2026-11-23). Revisión del repositorio hecha el 2026-11-23, sobre la rama `feature/latency-measurement` (último commit `fda39a3`). Mucho del trabajo reciente está **sin commitear** (migraciones, grafo, sesiones, evals, frontend Docker). Todo lo de abajo sale de leer el código y los archivos de resultados; lo que no se pudo verificar está marcado como "pendiente de confirmación".

Nota sobre la fuente del "contexto del proyecto": en el repositorio solo existe `.claude/MVP.md`, que describe el producto y las pantallas, pero **no menciona** Kokoro, Piper, Azure, Langfuse ni un cronograma. Esas referencias vienen del documento de contexto externo que mencionaste, que no está en el repo. Por eso las comparaciones de la sección 6 se hacen contra lo que tú describes, no contra un archivo.

## 1. Resumen

- El backend (FastAPI) ya recorre el flujo completo de un turno por voz: STT (Groq Whisper) → LLM (Gemini por defecto, Groq opcional) → TTS (Groq Orpheus con caché), orquestado con LangGraph y guardado en `sessions`/`turns` con migraciones Alembic. Los 71 tests pasan.
- Hay mediciones reales de latencia (1 corrida, 2026-11-23) y de gramática (4 corridas, solo una casi limpia). Son frágiles: 503 de Gemini y el límite diario de TTS de Groq ensucian los datos, y no hay WER.
- Faltan Langfuse, el endpoint para terminar sesión y cambiar `audio_consent`, el informe, el checkpointer en Postgres y la conexión del frontend con las sesiones (el frontend sigue en modo demo).

## 2. Stack real

| Componente | Tecnología usada | Archivo donde se ve |
|---|---|---|
| Lenguaje backend | Python 3.12 en Docker; el venv local es 3.14.3 (diferencia a revisar) | `backend/Dockerfile`, `backend/.venv` |
| API | FastAPI (`fastapi[standard]`), Pydantic v2, pydantic-settings | `backend/requirements.txt`, `backend/app/main.py` |
| Auth | fastapi-users, JWT en cookie httpOnly | `backend/app/users.py` |
| Base de datos | PostgreSQL 16 con imagen `pgvector/pgvector:pg16` en Docker; SQLite (`guako.db`) por defecto fuera de Docker y en tests. SQLAlchemy async + asyncpg/aiosqlite | `docker-compose.yml`, `backend/app/config.py`, `backend/app/db.py` |
| Migraciones | Alembic, 3 versiones (0001 baseline, 0002 `feedback_language`, 0003 `sessions`/`turns`) | `backend/alembic/versions/` |
| Orquestación | LangGraph (`StateGraph`), checkpointer `InMemorySaver` | `backend/app/conversation/graph.py` |
| LLM | Gemini `gemini-3.5-flash-lite` (por defecto) o Groq `openai/gpt-oss-20b`, elegido con `LLM_PROVIDER` | `backend/app/config.py`, `backend/app/llm/factory.py` |
| STT | Groq Whisper `whisper-large-v3`, idioma `en`, timestamps por palabra | `backend/app/stt/groq.py` |
| TTS | Groq Orpheus `canopylabs/orpheus-v1-english`, voz `hannah`, caché en disco por SHA-256 de voz+texto | `backend/app/tts/groq.py`, `backend/app/tts/cache.py`, `backend/app/tts/cached.py` |
| Observabilidad | **No encontrado.** Solo `logging` estándar (`app.llm`, `app.stt`, `app.tts`). Ninguna mención a Langfuse (ni LangSmith) en código, requirements ni README | grep en todo el repo |
| Frontend | Vite + JavaScript puro, monolito modular; Dockerfile con nginx (sin commitear) | `frontend/package.json`, `frontend/Dockerfile` |
| Tests | pytest 9 (instalado en el venv) | `backend/tests/` |

## 3. Decisiones tomadas (cambios respecto al contexto)

- **TTS: Groq Orpheus con caché, no Kokoro/Piper/Azure.** Confirmado. No hay ninguna referencia a Kokoro, Piper ni Azure en el código. El proveedor es `GroqOrpheusTTSProvider` envuelto en `CachedTTSProvider`. Motivo que dice el código: la caché ahorra cuota porque el plan gratuito de Groq permite solo 100 peticiones/día por organización (`backend/app/tts/cache.py`). Además hay un mensaje específico si falta aceptar los términos de Orpheus en la consola de Groq.
- **STT: Groq Whisper hospedado**, con pista de idioma `en` fijada. Comentario del código: sin pista, Whisper confunde el inglés con acento con otros idiomas (`backend/app/stt/groq.py`, `.env.example`).
- **Dos proveedores de LLM intercambiables** (Gemini y Groq) detrás de una interfaz común, con bucle de validación y reintentos propio. Los reintentos del SDK están desactivados a propósito: ocultarían errores de cuota y multiplicarían la latencia (`backend/app/llm/groq.py`).
- **El historial viene de la tabla `turns`, no del checkpointer.** El checkpointer es solo una caché en memoria; así un reinicio o un turno fallido no corrompe el contexto (`backend/app/conversation/graph.py`, `backend/app/sessions_api.py`).
- **Alembic gestiona el esquema**; ya no se crean tablas al arrancar la API (README).
- **Sin consentimiento de audio, el audio del usuario se borra tras transcribir** (`backend/app/sessions_api.py`).
- **Si falla STT, LLM o TTS no se guarda ningún turno.**
- **Docker Compose en la raíz** con tres servicios (`db`, `api`, `web`); antes estaba en `backend/`.
- **Nombre:** ver sección 6.

## 4. Resultados medidos

### Latencia
Origen: `backend/results/latency/20261123T051040Z-2a9e47.jsonl`. Medido el 2026-11-23 entre 05:10 y 05:20 UTC con `whisper-large-v3`, `gemini-3.5-flash-lite` y `canopylabs/orpheus-v1-english`. Los archivos están en `backend/results/`, que está en `.gitignore` (no se versionan).

Se intentaron 120 mediciones (20 audios × 3 repeticiones × 2 modos). Salieron bien 44 `cold` y 42 `warm`. Fallaron 34: 15 `cold` por límite de TTS de Groq (HTTP 429), 3 por 503 de Gemini, y 16 `warm` omitidos porque su `cold` falló. Cálculo propio (interpolación lineal) sobre las mediciones sin error, en milisegundos:

| Modo | n | STT p50 / p95 | LLM p50 / p95 | TTS p50 / p95 | Total p50 / p95 |
|---|---|---|---|---|---|
| cold (TTS real) | 44 | 557 / 1032 | 820 / 1360 | 1174 / 1467 | **2603 / 3549** |
| warm (TTS en caché) | 42 | 658 / 1057 | 890 / 1730 | 16 / 25 | **1499 / 2894** |

Lectura: el p50 de `cold` (2.6 s) cumple la meta de < 3 s del README, pero su p95 (3.5 s) la supera. El `warm` cumple ambas, aunque es un caso optimista, porque la caché solo ayuda con textos repetidos. Con menos de 30 válidas por modo el p95 no es estable; aquí hay 42–44, así que es aceptable pero salió de una sola corrida. Los datos están sesgados por los fallos (los audios afectados por el 429 no tienen `cold`). Son pendiente de confirmación: repetir cuando haya cuota de TTS.

### Evals de gramática
Origen: `backend/results/evals/*.jsonl` (4 corridas del 2026-11-23, 15:36–15:51 UTC, modelo `gemini-3.5-flash-lite`). Dataset: `backend/evals/grammar/cases.jsonl` (40 frases: 34 con errores, 6 correctas). Los archivos de resultados no guardan fecha propia; la fecha sale del `run_id`.

| Corrida | Casos con error de API | Errores esperados evaluados | Detectados (recall) | Con corrección correcta | Falsos positivos en frases correctas | Errores extra |
|---|---|---|---|---|---|---|
| `…153658Z-d7d3f0` (prueba, `--limit 3`) | 0 de 3 | 3 | 3 (100 %) | 3 | 0 de 0 | 0 |
| `…153752Z-bad00a` | 20 de 40 (503/429) | 17 | 16 (94 %) | 16 | 0 de 3 | 2 |
| `…154119Z-ff8a30` | 2 de 40 (503) | 32 | 30 (94 %) | 30 | 0 de 6 | 3 |
| `…155104Z-c9a654` | 10 de 40 (timeouts/503) | 26 | 24 (92 %) | 24 | 0 de 5 | 1 |

La mejor corrida es `ff8a30`: recall 30/32 = 93.8 %, 100 % de los detectados con la corrección esperada, 0 falsos positivos. Son conteos que calculé yo sobre los JSONL (el script imprime su propio resumen, que no está guardado). Ninguna corrida cubre los 40 casos sin errores, así que no hay una cifra "oficial" limpia. La "precisión" estricta no se mide: el script reporta `fix_accuracy`, `false_positive_rate` y errores extra.

### WER
**No encontrado.** No hay script de WER ni resultados. Existen 20 audios de latencia con su texto en `manifest.csv` (sirven de referencia), más un audio extra sin entrada en el manifest (`WhatsApp Ptt …ogg`, sin commitear), pero nadie calcula WER todavía.

### Pronunciación
**Fase hecha.** Lo que existe (rama `feature/pronunciacion-azure`):
- **Azure Speech, plan gratuito F0, región `brazilsouth`**, por el REST de audio corto con Pronunciation Assessment (no se usó el SDK ni wav2vec2). Devuelve puntajes por palabra y por fonema; el REST sí los trae en esa región.
- Análisis **en segundo plano por turno** (`turn_analyses`, dimensión `pronunciation`), detrás de la interfaz `PronunciationProvider`. Una llamada a la vez, reintentos para 429/503 y estado `failed` sin romper la sesión.
- **Cuota:** contador mensual en la base (`azure_speech_usage`); se detiene a 4 h 30 min de las 5 h gratuitas (`skipped_quota`). Sin audio guardado queda `skipped_no_audio`.
- **Informe:** puntaje y «palabras que costaron» (umbral 85, sin palabras funcionales) con IPA, el sonido más difícil y botón para escucharlas. Nota de justicia: el puntaje compara con un modelo de inglés estándar y nunca se juzga el acento.
- **Práctica «Ahora tú»:** 2 intentos por palabra, se aprueba con 90 o más y si Whisper entiende la palabra; al lograrla se bloquea. Reglas en el servidor (`word_practice`, migración 0009).
- **Referencia = lo que se quiso decir:** contexto de la conversación a Whisper y texto intencionado validado en código (`analysis/intent.py`).
- **Consentimiento de audio:** interruptor «Guardar mi audio» en Ajustes, activado por defecto; sin él la pronunciación no se mide y el informe lo explica.
- Migraciones 0008 y 0009 (probadas en SQLite y Postgres), ffmpeg en la imagen de Docker, 213 tests sin llamar a Azure.

**Eval (8 casos con audio, corrida el 2026-11-24):** con el criterio original (todas las palabras objetivo bajo 60) acertaron 0 de 8; 5 de 15 palabras objetivo salieron bajo 60. Azure es permisivo con diferencias finas de una vocal, por eso se endurecieron los umbrales. Resultados en `backend/results/evals/pronunciation-*.jsonl` (no versionados).

**Pendiente de esta fase:** probar con micrófono real las reglas estrictas, calibrar los umbrales con más datos, repetir la eval de gramática con el prompt `grammar_v2`, y permitir que la persona corrija lo que se entendió («Revisar lo dicho»). La ruta real de los casos es `backend/evals/grammar/pronunciation_cases.jsonl`.

## 5. Estado del MVP

| Punto | Estado | Evidencia |
|---|---|---|
| Proveedores LLM con salida validada y reintentos | **Hecho** | `llm/base.py`: valida con Pydantic y reintenta pasando el error al modelo (`LLM_MAX_RETRIES`, 2 por defecto); errores tipados y mapeados a HTTP. Tests en `test_llm.py`. No hay reintento ante 503/timeout (solo ante salida inválida): las corridas de evals lo muestran |
| STT con timestamps por palabra | **Hecho** | `stt/groq.py` (`timestamp_granularities=["word"]`), guardados en `turns.word_timestamps` |
| TTS con caché | **Hecho** | `tts/cached.py`, `tts/cache.py` |
| Medición de latencia: script | **Hecho** | `scripts/measure_latency.py`, `tests/test_latency.py` |
| Medición de latencia: resultados | **Parcial** | Una corrida, con 34 de 120 fallos (sección 4) |
| Evals: dataset | **Hecho** (gramática y pronunciación, con los 8 audios grabados) | 40 + 8 casos |
| Evals: script y resultados | **Parcial** | Scripts de gramática y de pronunciación hechos (la de pronunciación corrida una vez: 8 de 8 puntuados); sin script de WER; ninguna corrida de gramática completa sin errores |
| Pronunciación (Azure Speech) | **Hecho** | `app/pronunciation/`, `analysis/pronunciation.py`, `practice_api.py`, migraciones 0008 y 0009, `tests/test_pronunciation.py`, `test_word_practice.py`, `test_intent.py` |
| Grafo LangGraph: estado, nodos, checkpointer | **Parcial** | Estado `ConversationState`, 3 nodos (`transcribe → tutor_reply → synthesize`) y checkpointer; pero el checkpointer es `InMemorySaver` (se pierde al reiniciar) y el grafo es lineal: no hay nodos de corrección, informe ni "Repite, por favor" |
| Tablas `sessions` y `turns`, `audio_consent`, migraciones | **Hecho** | `PATCH /api/sessions/{id}` cambia `audio_consent` y `ended_at`; el frontend tiene el interruptor «Guardar mi audio» en Ajustes (activado por defecto) y lo aplica al crear la sesión. Migraciones hasta la 0009 |
| `POST /api/sessions/{id}/turns` | **Hecho** | `sessions_api.py` (multipart `audio`, valida formato y tamaño, 409 en turnos concurrentes). Tests en `test_sessions_api.py` |
| `feedback_language`: campo y `PATCH /api/users/me/settings` | **Hecho** | `db.py`, `users_api.py`, migración 0002, `test_user_settings.py`. Solo `es` y `en`; el MVP.md habla también de "mezcla" |
| `/health` | **Hecho** | `GET /health` y `/api/health` en `main.py`. Solo devuelve `ok`: no comprueba la base de datos |
| `.env.example` | **Hecho** | Cubre BD, LLM, STT, TTS y conversación |
| Tests y cómo correrlos | **Parcial** | 71 pasan (`python -m pytest -q` desde `backend/`, comprobado hoy). Pero `pytest` no está en `requirements.txt` y el README no explica cómo correr los tests |
| Langfuse / observabilidad | **Pendiente (no encontrado)** | — |
| Informe de fin de sesión, "Repite, por favor", exportar/borrar datos | **Pendiente (no encontrado)** | No hay endpoints |

## 6. Diferencias con el contexto actual

Dicen lo que el contexto afirma y el código no confirma, y viceversa.

**El contexto lo dice y el código no lo confirma**
- TTS con Kokoro/Piper o Azure: el código usa Groq Orpheus.
- Langfuse: no hay ni una línea.
- Frontend conectado al backend: el README dice que la app corre en modo demo (datos en el navegador, voz del navegador). No verifiqué esto ejecutándolo. El único uso de `/api/` en el frontend está en `auth/service.js` y `data/streak.js`; nada llama a `/api/sessions`.
- Cronograma y "semana actual": no hay ningún archivo con cronograma en el repo.

**El código tiene cosas que el contexto no menciona (o no confirmé)**
- Gemini como LLM por defecto y Groq como alternativa (pendiente de confirmación de cuál estaba planeado).
- Endpoint `POST /api/grammar/analyze` y sistema de rachas (`streaks`, `activity_days`, `/api/streak`), que son del frontend, no del plan de voz.
- Imagen `pgvector` en Docker, pero ninguna columna ni consulta usa vectores: no se ve el uso previsto.
- Conflicto de versión de Python: el Dockerfile usa 3.12 y el venv local 3.14.3. Los tests corren en 3.14; no se probó en 3.12.
- Dependencias sin fijar versión en `requirements.txt` y `pytest` ausente.
- Falta `ended_at`/`audio_consent` modificable (ver sección 5).

**Nombre del producto**
- Se usa **Guako** en todas partes: `README.md` (título), `.claude/MVP.md`, `<title>` del frontend, `FastAPI(title="Guako API")`, el prompt (`You are Guako…`) y `docker-compose.yml` (`name: guako`).
- "Tutor" aparece solo como rol interno (`TutorReply`, `tutor_reply`, `tutor_v1.txt`), no como nombre del producto. Decisión: el nombre real es Guako.

**Secretos**
- No encontré API keys en archivos versionados ni en el historial git (revisé los patrones `gsk_` y `AIza` con `git log -G` sobre todas las ramas, y que ningún `.env` haya sido commiteado). `backend/.env.example` solo trae valores de ejemplo.
- `backend/.env` existe en tu disco y **sí contiene claves reales** (de Gemini y Groq), pero está en `.gitignore` y no está rastreado. No copié ningún valor. Riesgo restante: el historial revisado es reciente, no auditado de forma exhaustiva; si alguna clave se pegó alguna vez en un chat o captura, rótala.
- `SECRET` por defecto en `config.py` es `cambia-esto-en-produccion`: si no hay `.env`, la API arranca con una firma débil. Los tests avisan de una clave HMAC de 25 bytes.

## 7. Próximos pasos

No hay cronograma en el repo, así que no puedo decir cuál es "la semana actual" (pendiente de confirmación). Este es el orden que sugiere el estado del código:

1. **Commitear lo existente** en commits separados: migraciones, grafo/sesiones, evals y frontend Docker. Mucho trabajo está solo en el disco.
2. **Cerrar la medición de latencia:** repetir la corrida cuando haya cuota de TTS, y decidir si se añade reintento ante 503/timeout del LLM (Gemini falló en 3 de las mediciones de latencia y en hasta 20 de 40 casos de evals).
3. **Cerrar los evals:** una corrida de gramática completa sin errores de API, y añadir el script de WER con los 20 audios del manifest. Los audios de pronunciación ya están grabados y la eval se corrió una vez (falta WER y una corrida limpia de gramática).
4. ~~Endpoints que faltan sobre sesiones (terminar sesión y cambiar `audio_consent`)~~ **Hecho:** `PATCH /api/sessions/{id}`.
5. **Checkpointer en Postgres** (`get_checkpointer()` es el único punto a cambiar) o confirmar que alcanza con el historial en `turns`.
6. **Observabilidad:** decidir si Langfuse sigue en el plan; si sí, integrarlo; si no, actualizar el contexto.
7. **Informe de fin de sesión** (gramática, pronunciación, fluidez, etc.) y la opción de feedback "mezcla".
8. **Conectar el frontend** con `/api/sessions` (hoy en modo demo).
9. **Higiene:** añadir `pytest` a `requirements.txt` (o un `requirements-dev.txt`), documentar cómo correr los tests, alinear la versión de Python, fijar versiones y hacer que `/health` compruebe la BD.
