# Notas para los revisores de Google Play y App Store

Texto listo para pegar en **Play Console → Contenido de la app → Acceso a la app** y en
**App Store Connect → App Review Information → Notes**. Las credenciales NO se guardan aquí.

## 1. Crear la cuenta de revisión (una vez)

```powershell
cd backend
.venv\Scripts\python.exe -m scripts.create_review_account --email revision@TU-DOMINIO
```

El script crea la cuenta contra el backend publicado (acepta los términos como cualquier usuario) e imprime
la contraseña **una sola vez**. Cópiala directo en las dos consolas. Después entra una vez con esa cuenta en el
teléfono y haz una conversación corta, para que el revisor encuentre la cuenta funcionando.

## 2. Texto para las notas (inglés: los revisores lo leen en inglés)

```
Guako is an English speaking-practice app: the learner talks by voice with an AI tutor (Guako)
and gets a report with pronunciation, grammar and fluency feedback.

Test account
  Email:    <pegar aquí>
  Password: <pegar aquí>

How to test
  1. Log in with the account above.
  2. Tap "Start a conversation", choose a level and a topic, tap "Let's talk!", and allow microphone access when asked.
     The microphone is only used while the learner holds the talk button.
  3. Hold the talk button, say a sentence in English, release it. Guako answers by voice.
  4. Tap "End conversation" to see the report (it can take a few seconds to be ready).

AI safety
  - Learner messages and AI replies pass through a moderation filter.
  - Every AI reply has a flag button ("Report this reply") in the conversation and in the review screen;
    reports are stored and reviewed by the team.

Account deletion
  Settings > "Delete my account and data". It deletes the account and all its data on the server
  (conversations, recordings, reports, consents) immediately.

Privacy policy: https://<web-domain>/privacy
Contact: <correo de contacto>
```

## 3. Lo mismo en español (por si la consola lo pide en español)

```
Guako es una app para practicar inglés hablado: el usuario conversa por voz con un tutor de IA (Guako)
y recibe un informe de pronunciación, gramática y fluidez.

Cuenta de prueba
  Correo:     <pegar aquí>
  Contraseña: <pegar aquí>

Cómo probarla
  1. Inicia sesión con la cuenta de arriba.
  2. Toca "Empezar conversación", elige nivel y tema, toca "¡Vamos a hablar!" y permite el micrófono cuando se pida.
     El micrófono solo se usa mientras se mantiene pulsado el botón para hablar.
  3. Mantén pulsado el botón, di una frase en inglés y suéltalo. Guako responde con voz.
  4. Toca "Terminar conversación" para ver el informe (puede tardar unos segundos).

Seguridad de la IA
  - Los mensajes del usuario y las respuestas de la IA pasan por un filtro de moderación.
  - Cada respuesta de la IA tiene un botón para reportarla ("Reportar esta respuesta") en la conversación
    y en la revisión; los reportes se guardan y los revisa el equipo.

Borrar la cuenta
  Ajustes > "Borrar mi cuenta y mis datos". Borra al instante la cuenta y todos sus datos en el servidor
  (conversaciones, grabaciones, reportes, consentimientos).

Política de privacidad: https://<dominio-web>/privacidad
Contacto: <correo de contacto>
```

## 4. Revisar los reportes de respuestas

Con una cuenta de administrador (`is_superuser`): `GET /api/admin/reports` devuelve los últimos reportes con el
texto de la respuesta reportada.
