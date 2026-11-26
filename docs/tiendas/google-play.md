# Google Play: todo lo que se llena en Play Console

Respuestas preparadas a partir de lo que la app hace hoy (código y política de privacidad). Si cambia algo
(nuevo proveedor, anuncios, pagos, otro permiso), actualiza este archivo y el formulario.
Antes de enviar, compara con lo que pide la consola ese día: Google cambia los formularios.

`<dominio-web>` = el dominio de la web en Vercel.

---

## 1. Orden recomendado

1. Crear la cuenta de desarrollador (pago único) — **lo haces tú**. Cuenta personal u organización:
   como organización (con D-U-N-S) te saltas la prueba cerrada obligatoria del punto 5.
2. `npm run android:keystore` (una vez) → `npm run android:bundle` → sube
   `frontend/android/app/build/outputs/bundle/release/app-release.aab`. Activa **Play App Signing** (Google
   guarda la llave final; la tuya es solo de subida).
3. Llenar "Contenido de la app" (puntos 2, 3 y 4).
4. Ficha de la tienda (punto 6).
5. Prueba cerrada (punto 5) → producción.

---

## 2. Seguridad de los datos (Data safety)

**¿La app recopila o comparte datos de usuario?** Sí.
**¿Todos los datos se cifran en tránsito?** Sí (todo va por HTTPS).
**¿Ofreces una forma de pedir que se borren los datos?** Sí.
**Cuentas:** la app permite crear cuenta (usuario + correo + contraseña).
- Enlace para borrar la cuenta: `https://<dominio-web>/delete-account`
- La app también lo permite dentro: Ajustes → "Borrar mi cuenta y mis datos".

**¿Se comparten datos con terceros?** No. Groq, OpenAI, Google (Gemini), Azure Speech, Langfuse y el
alojamiento procesan los datos **en nombre de Guako** (proveedores de servicio): según las reglas de Play eso
no cuenta como "compartir". No hay anuncios ni venta de datos.

| Tipo de dato (Play) | ¿Se recopila? | Obligatorio | Para qué | Notas |
|---|---|---|---|---|
| Información personal → **Correo electrónico** | Sí | Sí | Funcionalidad de la app, Gestión de la cuenta | Inicio de sesión |
| Información personal → **Nombre** | Sí | Sí | Funcionalidad de la app, Gestión de la cuenta | El nombre de usuario que elige la persona |
| Audio → **Grabaciones de voz o sonido** | Sí | Sí | Funcionalidad de la app | Se transcribe para conversar. Guardarlo (para medir pronunciación) es opcional y con permiso |
| Actividad en la app → **Interacciones con la app** | Sí | Sí | Funcionalidad de la app, Analíticas | Progreso, racha, ejercicios |
| Actividad en la app → **Otro contenido generado por el usuario** | Sí | Sí | Funcionalidad de la app, Analíticas, Prevención de fraudes/seguridad | Transcripciones, comentarios de reportes; moderación automática |

No se recopilan: ubicación, contactos, fotos, archivos, calendario, salud, información financiera,
identificadores del dispositivo, historial de navegación.

> Ojo: el registro de consentimientos guarda la IP como prueba (Ley 1581). No se usa para ubicar a nadie, así
> que no se declara como ubicación; si algún día se usa para eso, hay que declarar "Ubicación aproximada".

---

## 3. Contenido de la app (otras declaraciones)

| Sección | Respuesta |
|---|---|
| Política de privacidad | `https://<dominio-web>/privacidad` |
| Acceso a la app | Toda la funcionalidad está detrás de un inicio de sesión → credenciales y texto de `notas-revision.md` |
| Anuncios | La app **no** contiene anuncios |
| Público objetivo | **18 años o más** (los Términos dicen que el servicio es para mayores de 18). Elegir menores activa la política de Familias, con reglas extra para IA y datos |
| ¿Atrae a niños sin querer? | No |
| Apps de noticias | No |
| Apps de salud | No |
| Funciones financieras | Ninguna |
| App gubernamental | No |
| Contenido generado por IA | Sí: la app genera respuestas con IA. Hay moderación automática y un botón en cada respuesta para reportarla (requisito de la política de IA generativa) |
| Permisos sensibles | Micrófono (`RECORD_AUDIO`), usado mientras la persona mantiene pulsado el botón para hablar. Notificaciones (`POST_NOTIFICATIONS`) solo si activa el recordatorio diario. **No** usa alarmas exactas (`SCHEDULE_EXACT_ALARM` se quita del manifiesto), así que no hay que declarar nada de alarmas |

---

## 4. Clasificación de contenido (cuestionario IARC)

- Correo de contacto: el de `frontend/src/features/legal/content.js`.
- Categoría: **Referencia, noticias o educación** (si la consola no la ofrece, "Todos los demás tipos de app").
- Respuestas: violencia **No** · miedo **No** · sexualidad **No** · lenguaje soez **No** · drogas, alcohol,
  tabaco **No** · apuestas **No** · compras digitales **No**.
- ¿Los usuarios pueden interactuar o intercambiar contenido **entre sí**? **No** (cada persona habla solo con
  la IA; nadie ve lo de otro).
- ¿Comparte la ubicación del usuario con otros usuarios? **No**.
- Si pregunta por chatbots o contenido generado por IA: **Sí**, con moderación y opción de reportar.

Resultado esperado: clasificación baja (todo público / PEGI 3–12 según región). Si la IA lo sube por el
chatbot, no pasa nada: el público objetivo ya es 18+.

---

## 5. Prueba cerrada (solo cuentas personales nuevas)

Las cuentas personales creadas después de noviembre de 2023 deben tener una **prueba cerrada con al menos 12
testers inscritos durante 14 días seguidos** antes de pedir acceso a producción (verifica la cifra en la
consola: Google la ha cambiado antes).

1. Testing → Closed testing → crear pista "Pruebas cerradas" → subir el AAB.
2. Testers: lista de correos de Google (amigos, compañeros) o un Grupo de Google. Necesitas **12 que acepten**
   la invitación con el enlace de inscripción y **no se salgan** en 14 días (invita a 15–20 por margen).
3. Pídeles usarla de verdad un par de veces: Google pregunta al final qué se probó y qué se cambió.
4. Pasados los 14 días: Dashboard → "Apply for production" (responde el cuestionario sobre la prueba).

Mensaje para invitar testers (ES):
```
¡Hola! Estoy publicando Guako, una app para practicar inglés hablando con una IA.
¿Me ayudas a probarla 2 semanas? 1) Entra a este enlace con tu cuenta de Google: <enlace de inscripción>
2) Instálala desde Play Store. 3) Haz una conversación corta cuando puedas. No la desinstales antes de 14 días.
¡Gracias!
```

---

## 6. Ficha de la tienda

Archivos listos en `docs/tiendas/capturas/play-store/<es|en>/`:
- Ícono 512×512: `frontend/assets/play-store-icon-512.png`
- Gráfico destacado 1024×500: `feature-graphic.png`
- Capturas de teléfono 1242×2208: `01-inicio.png` … `06-practica.png`
- Categoría: **Educación**. Etiquetas: aprendizaje de idiomas, inglés.

### Español (Latinoamérica) — idioma principal

**Nombre (máx. 30):** `Guako: habla inglés sin pena`

**Descripción breve (máx. 80):**
`Practica inglés hablando con una IA y recibe correcciones de pronunciación.`

**Descripción completa:**
```
Guako es tu compañero para perderle el miedo a hablar inglés.

Elige un tema (viajes, trabajo, vida diaria, restaurante o el que quieras) y conversa por voz con Guako,
una guacamaya con inteligencia artificial que te responde como en una conversación real.

Al terminar recibes un informe con:
• Pronunciación: qué palabras mejorar y cómo decirlas.
• Gramática: tus errores marcados, con la corrección y una explicación corta.
• Fluidez y comprensión: cómo vas en cada conversación.

Además:
• Práctica de palabras y frases difíciles, con ejercicios hechos a partir de tus propios errores.
• Tu progreso y tu racha de días practicando.
• Revisión completa de cada conversación.
• En español o en inglés.

Tu privacidad importa: guardar tu voz es opcional, y puedes borrar tu cuenta y todos tus datos cuando
quieras desde Ajustes.

Guako usa inteligencia artificial: puede equivocarse. Si una respuesta te parece incorrecta u ofensiva,
repórtala con la bandera que tiene cada respuesta.
```

### English (United States)

**Name (max 30):** `Guako: speak English`

**Short description (max 80):**
`Practice English by talking with an AI and get pronunciation feedback.`

**Full description:**
```
Guako helps you lose the fear of speaking English.

Pick a topic (travel, work, daily life, restaurant or your own) and talk by voice with Guako, a macaw
powered by artificial intelligence that answers you like a real conversation partner.

When you finish you get a report with:
• Pronunciation: which words to improve and how to say them.
• Grammar: your mistakes highlighted, with the correction and a short explanation.
• Fluency and listening: how you are doing in each conversation.

Plus:
• Practice for hard words and phrases, with exercises built from your own mistakes.
• Your progress and your daily practice streak.
• A full review of every conversation.
• In Spanish or English.

Your privacy matters: keeping your voice recordings is optional, and you can delete your account and all
your data at any time from Settings.

Guako uses artificial intelligence and can make mistakes. If a reply looks wrong or offensive, report it
with the flag on every reply.
```
