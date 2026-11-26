# App Store: todo lo que se llena en App Store Connect

Respuestas preparadas a partir de lo que la app hace hoy. Deben coincidir con el privacy manifest
(`frontend/ios/App/App/PrivacyInfo.xcprivacy`) y con la ficha de Google Play (`google-play.md`).
Antes de enviar, compara con lo que pide App Store Connect ese día.

`<dominio-web>` = el dominio de la web en Vercel.

---

## 1. Orden recomendado

1. **Apple Developer Program** (pago anual) — lo haces tú. Anota el **Team ID** (Membership).
2. developer.apple.com → Identifiers → registrar el App ID `com.guako.app` (capacidad: Push Notifications
   no hace falta; las notificaciones del recordatorio son locales).
3. App Store Connect → Apps → "+" → nueva app: plataforma iOS, nombre, idioma principal Español (México o
   España), bundle id `com.guako.app`, SKU `guako-ios`.
4. App Store Connect → Users and Access → Integrations → crear una **API key** (rol App Manager). Carga en
   GitHub los secretos `APPLE_TEAM_ID`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`.
5. `npm run version:mobile` (desde el segundo envío) → commit y push → GitHub → Actions → **iOS** → Run
   workflow con `upload = true`. La compilación aparece en TestFlight en ~15 min.
6. Probarla en TestFlight en un iPhone real (micrófono, login, notificación del recordatorio, notch).
7. Llenar los puntos 2 a 5 de este documento y enviar a revisión.

Primero conviene correr el workflow con `upload = false`: solo comprueba que compila y no necesita secretos.

---

## 2. Privacidad de la app (etiquetas de App Store Connect)

**¿Recopilas datos?** Sí. **¿Se usan para rastrear (tracking)?** No, ninguno. Sin anuncios ni IDFA.

| Tipo (Apple) | Vinculado a la persona | Rastreo | Para qué |
|---|---|---|---|
| Información de contacto → **Correo electrónico** | Sí | No | Funcionalidad de la app |
| Información de contacto → **Nombre** | Sí | No | Funcionalidad de la app (nombre de usuario) |
| Contenido del usuario → **Datos de audio** | Sí | No | Funcionalidad de la app |
| Contenido del usuario → **Otro contenido del usuario** | Sí | No | Funcionalidad de la app, Analíticas |
| Uso → **Interacción con el producto** | Sí | No | Funcionalidad de la app, Analíticas |

No se recopila: ubicación, contactos, fotos, salud, finanzas, identificadores del dispositivo, historial
de navegación o búsqueda, diagnósticos del dispositivo.

- **URL de la política de privacidad:** `https://<dominio-web>/privacidad`
- **Borrar la cuenta (guía 5.1.1(v)):** dentro de la app, Ajustes → "Borrar mi cuenta y mis datos". Página
  pública: `https://<dominio-web>/borrar-cuenta`.

---

## 3. Clasificación por edad

Respuestas del cuestionario: violencia (caricatura, realista, gráfica) **Ninguna** · contenido sexual o
desnudez **Ninguno** · lenguaje soez **Ninguno** · terror o miedo **Ninguno** · drogas, alcohol, tabaco
**Ninguno** · temas médicos **Ninguno** · apuestas y concursos **No** · contenido para adultos **No**.

- ¿Acceso web sin restricciones? **No** (la app no abre un navegador libre).
- ¿Contenido generado por usuarios o comunicación entre usuarios? **No** (cada persona habla solo con la IA).
- Si pregunta por **chatbot / contenido generado por IA**: **Sí**, con moderación automática y botón para
  reportar cada respuesta.
- Controles parentales / verificación de edad: no.

Calificación sugerida: la que resulte del cuestionario. Los Términos dicen 18+, así que en "Made for Kids"
responde **No**.

---

## 4. Ficha de la tienda

Archivos en `docs/tiendas/capturas/`:
- iPhone 6,9" (1320×2868): `app-store/<es|en>/01-inicio.png` … `06-practica.png`
- iPad 13" (2064×2752): `app-store-ipad/<es|en>/…` (el proyecto es universal: iPhone + iPad).
  Si prefieres solo iPhone: Xcode → Targets → App → General → Supported Destinations → quitar iPad
  (y entonces no hacen falta estas capturas).
- Ícono 1024×1024: lo toma de la compilación (`frontend/assets/icon-only.png`).

| Campo | Valor |
|---|---|
| Categoría principal | Educación |
| Categoría secundaria | Referencia (opcional) |
| URL de soporte | `https://<dominio-web>/privacidad` (tiene el correo de contacto) |
| URL de marketing | `https://<dominio-web>` |
| Copyright | `2026 Guako` |
| Precio | Gratis |
| Cifrado (export compliance) | Ya declarado en `Info.plist` (`ITSAppUsesNonExemptEncryption = false`): solo HTTPS |
| Derechos de contenido | No contiene contenido de terceros que requiera derechos |

### Español

- **Nombre (30):** `Guako: habla inglés sin pena`
- **Subtítulo (30):** `Practica conversación con IA`
- **Palabras clave (100):** `inglés,hablar,pronunciación,conversación,idiomas,practicar,acento,gramática,tutor,IA,fluidez`
- **Texto promocional (170):** `Conversa por voz con Guako y recibe un informe de pronunciación y gramática después de cada práctica.`
- **Descripción:** la misma descripción completa de `google-play.md` §6 (español).

### English

- **Name (30):** `Guako: speak English`
- **Subtitle (30):** `Speak English with an AI tutor`
- **Keywords (100):** `english,speaking,pronunciation,conversation,language,practice,accent,grammar,tutor,AI,fluency`
- **Promotional text (170):** `Talk by voice with Guako and get a pronunciation and grammar report after every practice.`
- **Description:** the same full description as `google-play.md` §6 (English).

---

## 5. Información para la revisión

- **Cuenta de prueba y notas:** `notas-revision.md` (crear la cuenta con el script y pegar el texto en inglés).
- **Contacto:** nombre, teléfono y correo de quien responde a Apple.

### Guía 4.2 (funcionalidad mínima): qué hace a Guako una app y no "una web en una caja"

Para pegar en las notas si Apple pregunta, o para responder un rechazo por 4.2:

```
Guako is built for mobile use and uses native capabilities:
- Native microphone capture with a push-to-talk button and haptic feedback when recording starts and stops.
- Daily streak reminders with local notifications (Settings > Daily reminder), skipped on days the learner
  already practiced.
- Native status bar, safe areas (notch and home indicator) and launch screen; no browser chrome or external links.
- The core experience is a real-time voice conversation with an AI tutor, plus a personalized report,
  pronunciation practice and progress tracking that the learner uses daily.
```
