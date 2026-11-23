# Guako

- `frontend/` — Vite + JavaScript puro
- `backend/` — FastAPI (Python)

## Arrancar

Backend (http://127.0.0.1:8000, docs en `/docs`):

```powershell
cd backend
python -m venv .venv   # solo la primera vez
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt   # solo la primera vez
copy .env.example .env            # solo la primera vez; cambia SECRET
fastapi dev app/main.py
```

Frontend (http://localhost:5173):

```powershell
cd frontend
npm run dev
```

El frontend redirige `/api/*` al backend (ver `frontend/vite.config.js`).

## Medir la latencia del pipeline de audio (backend)

Mide STT → LLM → TTS con las APIs reales (consume cuota gratuita; Groq TTS permite 100 llamadas/día). Los 20 audios (WAV u OGG) y su `manifest.csv` van en `backend/evals/audio/latency/` (nombres `lat_NN_<length>_<condition>`).

```powershell
cd backend
python -m scripts.measure_latency --runs 3
```

Opciones: `--runs N` (por defecto 3), `--pause-s S` (espera de 3 s antes de cada turno, fuera de la medición, para no chocar con el límite de peticiones por minuto de Groq), `--limit N` (solo los primeros N audios, para una prueba barata), `--audio-dir`, `--manifest`, `--results-dir`. Cada corrida escribe `backend/results/latency/<run_id>.jsonl` (nunca sobrescribe corridas anteriores) e imprime un resumen.

Cada audio se mide en dos modos: `cold` (caché de TTS vacía, llamada real al TTS) y `warm` (caché llena: el TTS se sirve del disco; reutiliza el texto de la respuesta del `cold`, porque el LLM no responde idéntico dos veces).

Columnas de cada línea del JSONL:

| Columna | Significado |
|---|---|
| `run_id`, `timestamp_utc` | Identificador de la corrida y hora UTC de la medición |
| `file`, `condition`, `audio_seconds` | Audio medido, su condición (`short_clean`, `medium_noisy`…) y su duración |
| `mode` | `cold` o `warm` |
| `stt_ms`, `llm_ms`, `tts_ms` | Tiempo de cada etapa en milisegundos |
| `total_ms` | Desde que empieza el turno hasta que el audio de respuesta está listo (`null` si hubo error) |
| `tts_cache_hit` | Si el TTS salió de la caché |
| `retries` | Reintentos del LLM por salida inválida |
| `error` | Mensaje del error, o `null` |
| `stt_model`, `llm_model`, `tts_model` | Modelos usados |

**Cómo leer p50 y p95:** p50 (mediana) es el tiempo típico: la mitad de los turnos fue más rápida. p95 es el tiempo que el 95 % de los turnos no supera: refleja los casos lentos que el usuario sí nota. La meta del MVP es p50 < 3 s y p95 cercano a 3 s en `total_ms`. Con menos de 30 mediciones válidas por modo el p95 no es estable (el resumen lo advierte). Para comparar cambios de modelo, prompt o caché, corre antes y después con las mismas opciones y compara los resúmenes.

## Estructura del frontend (monolito modular)

Cada cosa vive en su módulo, y cada pieza visual tiene su carpeta con su `.js` y su `.css` juntos. Los imports usan el alias `@/` (= `frontend/src/`).

```
frontend/src/
├── main.js                 Entrada: estilos globales, landing ↔ app según la URL y clics globales
├── core/                   Infraestructura sin interfaz (no importa nada de features/ ni shared/)
│   ├── i18n.js             t(), setLang(), addMessages()
│   ├── router.js           navigate(), matchPath()
│   └── lifecycle.js        Limpieza de listeners y temporizadores
├── shared/                 Reutilizable por cualquier módulo
│   ├── styles/             tokens.css (colores, fuentes), base.css, buttons.css (.btn, .link)
│   ├── components/modal/   Modal base (foco, Esc, bloqueo de scroll)
│   └── assets/             brand/ (logo) e illustrations/ (roles, usadas por landing y app)
└── features/               Un módulo por área. Cada uno expone su API en index.js
    ├── landing/            Página pública "/"
    │   ├── sections/       hero, roles, how, cta (una carpeta por sección)
    │   ├── components/     navbar, card-stack, side-columns, phrase-carousel, voice-demo,
    │   │                   logo-marquee, feathers, mark
    │   ├── lib/            scroll-reveal.js (entrada ligada al scroll)
    │   ├── assets/         benefits/, how/
    │   └── i18n/           es.js, en.js
    ├── auth/               Login y registro (usuario, correo, contraseña y confirmación) (service.js + auth-modal)
    ├── legal/              Términos y Privacidad (content.js + legal-modal)
    └── app/                Aplicación con sesión "/app/..."
        ├── routes.js       Rutas → views/<nombre>/
        ├── shell/          Menú lateral, barra superior, barra inferior móvil
        ├── views/          Una carpeta por pantalla (inicio, preparar, conversacion, informe…)
        ├── components/     icon, ring, toast, confirm-dialog
        ├── styles/         buttons, card, progress-bar (estilos solo-CSS de la app)
        ├── data/           store.js (datos), seed.js (contenido demo), setup.js (borrador)
        ├── services/       tts.js (voz del navegador)
        ├── utils/          html.js (esc), format.js, explain.js, scores.js
        └── i18n/           es.js, en.js (bajo la clave `app`)
```

Las reglas completas (qué va dónde, cómo crear una sección, un componente o una pantalla) están en la skill `.claude/skills/guako-arquitectura/SKILL.md`.

## Idiomas, login y textos legales (frontend)

- **Idioma ES/EN:** cada módulo tiene sus textos en su carpeta `i18n/` (`es.js` y `en.js`) y los registra en su `index.js`. El selector del navbar guarda la elección en el navegador.
- **Login, registro (OTP) y recuperar contraseña:** son modales (`frontend/src/features/auth/`). Hoy corren en **modo demo** (`features/auth/service.js`): no envían correos y el código válido es `123456`. Para conectarlos al backend real, expón los endpoints descritos al inicio de `service.js` y define `VITE_AUTH_MOCK=false`.
- **Términos y Política de privacidad:** `frontend/src/features/legal/content.js` (ES/EN). Son un **borrador**: cambia el correo de contacto y el país en `LEGAL_CONFIG` y haz que los revise un abogado antes de publicarlos. Enlaces directos: `#terminos` y `#privacidad`.

## La aplicación (frontend)

Vive en `/app/...` (la landing sigue en `/`). Se basa en `.claude/MVP.md`: Entrar, Inicio, Preparar conversación, Conversación, Informe, Revisar lo dicho, Progreso, Mis conversaciones, Práctica y Ajustes.

- **Código:** `frontend/src/features/app/` (rutas en `routes.js`, menú en `shell/`, una pantalla por carpeta en `views/`).
- **Modo demo:** mientras no exista el backend, los datos de ejemplo viven en el navegador (`data/store.js`, contenido en `data/seed.js`), la voz del usuario **no se graba ni se evalúa** (la conversación usa respuestas de ejemplo) y la voz de Guako usa la síntesis de voz del navegador. Cuando exista el backend, `store.js` y `seed.js` son lo que se reemplaza por llamadas a la API.
- **Conversación:** se habla manteniendo presionada la barra espaciadora (o el botón grande en pantallas táctiles).
