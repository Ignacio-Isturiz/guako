// Service worker mínimo de la web instalable (Guako).
// Chrome lo usa para ofrecer "Instalar aplicación" directo desde el botón de la landing.
// No guarda nada en caché: todo va a la red como siempre. Solo si no hay conexión al abrir una
// página, responde con un aviso sencillo en vez de la pantalla de error del navegador.
// También muestra el recordatorio diario de racha que envía el backend por Web Push (backend/app/push.py).
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

const OFFLINE = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guako</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b2a6b;color:#fff;font:600 1.1rem system-ui,sans-serif;text-align:center;padding:24px}</style></head>
<body><p>Sin conexión. Revisa tu internet y vuelve a abrir Guako.<br><small>No connection. Check your internet and open Guako again.</small></p></body></html>`

self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })))
})

// Recordatorio de racha: el backend manda { title, body, url }
self.addEventListener('push', (e) => {
  let data = {}
  try {
    data = e.data ? e.data.json() : {}
  } catch {
    data = { body: e.data?.text() }
  }
  e.waitUntil(
    self.registration.showNotification(data.title || 'Guako', {
      body: data.body || '',
      icon: '/icons/icon-192.png',
      badge: '/icons/badge-96.png',
      tag: 'guako-reminder', // uno nuevo reemplaza al anterior en vez de apilarse
      data: { url: data.url || '/app/inicio' },
    }),
  )
})

// Al tocarlo: abre la app (o la trae al frente si ya estaba abierta) en la pantalla indicada
self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const url = new URL(e.notification.data?.url || '/app/inicio', self.location.origin).href
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      const open = list.find((c) => new URL(c.url).origin === self.location.origin)
      if (open) return open.focus().then((c) => c.navigate?.(url))
      return self.clients.openWindow(url)
    }),
  )
})
