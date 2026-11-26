// Capturas de pantalla para las tiendas, a resolución real de teléfono, en español e inglés.
//
//   1. Arranca el frontend en modo demo (datos de ejemplo, sin backend):
//        $env:VITE_AUTH_MOCK='true'; $env:VITE_DEMO_MODE='true'; npm run dev -- --port 5175
//   2. node scripts/store-screenshots.mjs            (otra URL: --url http://localhost:5175)
//
// Usa Microsoft Edge (o Chrome) sin ventana por el protocolo de depuración: no instala nada.
// Salida en docs/tiendas/capturas/<tienda>/<idioma>/NN-pantalla.png
//   app-store  1320×2868  iPhone 6,9" (el tamaño que App Store pide como principal)
//   play-store 1242×2208  9:16 (Google Play no acepta capturas más alargadas que 2:1)
//   app-store-ipad 2064×2752  iPad 13" (el proyecto iOS es universal: App Store las pide)
// y el gráfico destacado de Google Play (1024×500) desde scripts/feature-graphic.html:
//   play-store/<idioma>/feature-graphic.png
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 ? process.argv[i + 1] : fallback
}
const BASE = arg('url', 'http://localhost:5175')
const OUT = fileURLToPath(new URL('../../docs/tiendas/capturas', import.meta.url))
const PORT = 9333

const DEVICES = {
  'app-store': { width: 440, height: 956, scale: 3 },
  'play-store': { width: 414, height: 736, scale: 3 },
  'app-store-ipad': { width: 1032, height: 1376, scale: 2 },
}
const SCREENS = [
  ['01-inicio', '/app/inicio'],
  ['02-preparar', '/app/preparar'],
  ['03-informe', '/app/informe/c_seed_1'],
  ['04-revision', '/app/revision/c_seed_1'],
  ['05-progreso', '/app/progreso'],
  ['06-practica', '/app/practica'],
]
const LANGS = ['es', 'en']
const DEMO_USER = { name: 'Valentina', email: 'valentina@example.com' }

const BROWSERS = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
]
const browserPath = BROWSERS.find(existsSync)
if (!browserPath) throw new Error('No se encontró Edge ni Chrome')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const profile = await mkdtemp(join(tmpdir(), 'guako-shots-'))
const browser = spawn(browserPath, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  '--hide-scrollbars',
  '--no-first-run',
  'about:blank',
])

// Conexión CDP a la primera pestaña
let target
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200)
  target = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    .then((r) => r.json())
    .then((list) => list.find((t) => t.type === 'page'))
    .catch(() => null)
}
if (!target) throw new Error('El navegador no abrió el puerto de depuración')
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let seq = 0
const waiting = new Map()
ws.addEventListener('message', (e) => {
  const msg = JSON.parse(e.data)
  if (msg.id && waiting.has(msg.id)) {
    const { resolve, reject } = waiting.get(msg.id)
    waiting.delete(msg.id)
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result)
  }
})
const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++seq
    waiting.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params }))
  })
const evaluate = (expression) => send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
const go = async (path) => {
  await send('Page.navigate', { url: BASE + path })
  await sleep(2200) // fuentes, imágenes y animaciones de entrada
}

try {
  await send('Page.enable')
  await go('/')
  for (const [store, d] of Object.entries(DEVICES)) {
    await send('Emulation.setDeviceMetricsOverride', {
      width: d.width,
      height: d.height,
      deviceScaleFactor: d.scale,
      mobile: true,
    })
    for (const lang of LANGS) {
      // Sesión de demo + idioma; luego se cierra el aviso "Modo demo" con su propio botón
      await evaluate(`localStorage.setItem('guako.session', ${JSON.stringify(JSON.stringify(DEMO_USER))});
        localStorage.setItem('guako.lang', '${lang}')`)
      await go('/app/inicio')
      await evaluate(`[...document.querySelectorAll('button,a')].find((b) => ['Entendido', 'Got it'].includes(b.textContent.trim()))?.click()`)
      const dir = join(OUT, store, lang)
      await mkdir(dir, { recursive: true })
      for (const [name, path] of SCREENS) {
        await go(path)
        const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
        await writeFile(join(dir, `${name}.png`), Buffer.from(data, 'base64'))
        console.log(`${store}/${lang}/${name}.png`)
      }
    }
  }

  // Gráfico destacado de Google Play: 1024×500 exactos, sin escala
  await send('Emulation.setDeviceMetricsOverride', { width: 1024, height: 500, deviceScaleFactor: 1, mobile: false })
  const graphic = pathToFileURL(fileURLToPath(new URL('./feature-graphic.html', import.meta.url))).href
  for (const lang of LANGS) {
    await send('Page.navigate', { url: `${graphic}?lang=${lang}` })
    await sleep(2500) // fuentes de Google Fonts
    const { data } = await send('Page.captureScreenshot', { format: 'png' })
    await writeFile(join(OUT, 'play-store', lang, 'feature-graphic.png'), Buffer.from(data, 'base64'))
    console.log(`play-store/${lang}/feature-graphic.png`)
  }
} finally {
  ws.close()
  browser.kill()
  await sleep(500)
  await rm(profile, { recursive: true, force: true }).catch(() => {})
}
