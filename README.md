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
