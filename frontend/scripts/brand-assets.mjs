// Genera las imágenes base de la app móvil a partir del logo (src/shared/assets/brand/guako-logo.png):
//   assets/icon-only.png        1024×1024 guacamaya completa sobre el azul del logo, sin transparencia (iOS, App Store, Play Store 512 se saca de aquí)
//   assets/icon-foreground.png  1024×1024 capa delantera del ícono adaptable de Android (dentro de la zona segura)
//   assets/icon-background.png  1024×1024 capa de fondo (degradado azul del logo)
//   public/icons/*              íconos de la web instalable (manifest) y apple-touch-icon
//   assets/splash.png           2732×2732 pantalla de inicio (y splash-dark.png igual)
//   assets/play-store-icon-512.png  ícono de la ficha de Google Play
// Después `capacitor-assets generate` saca de aquí todos los tamaños de Android e iOS (npm run assets:mobile).
//
// El logo original mide 512 px: el ícono de 1024 queda ampliado ×2. Si hay un original más grande, ponlo en
// lugar de guako-logo.png (mismo dibujo) y vuelve a correr el script.
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import sharp from 'sharp'

const root = fileURLToPath(new URL('..', import.meta.url))
const LOGO = `${root}src/shared/assets/brand/guako-logo.png`
const OUT = `${root}assets`
const SPLASH_BG = '#0b2a6b' // --navy de tokens.css, el mismo de capacitor.config.json

// El logo sin el margen transparente que lo rodea
const trimmed = await sharp(LOGO).trim({ threshold: 0 }).toBuffer()
const square = (size, background) => sharp({ create: { width: size, height: size, channels: 4, background } })
const fit = (size) => sharp(trimmed).resize(size, size, { fit: 'cover', kernel: 'lanczos3' }).toBuffer()

await mkdir(OUT, { recursive: true })

// Íconos: la guacamaya COMPLETA (cresta incluida) sobre el azul del logo, llenando todo el ícono, sin
// bordes blancos. Se separa la guacamaya del cuadro azul del logo (así no se ve la línea de su borde
// redondeado) y se pone sobre un degradado del mismo azul, apoyada abajo: el cuerpo sale por el borde
// inferior, como en el logo. Cada sistema pone su máscara (círculo, cuadrado redondeado…) encima.
const ICON_TOP = '#002d70' // azul de arriba del logo (medido)
const ICON_BOTTOM = '#01255d' // azul de abajo del logo (medido)
const parrot = await (async () => {
  const { data, info } = await sharp(trimmed).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
  const { width: W, height: H } = info
  const out = Buffer.from(data)
  const opaque = (x, y) => x >= 0 && y >= 0 && x < W && y < H && data[(y * W + x) * 4 + 3] === 255
  const EDGE = 8 // px del borde del cuadro azul (y su halo claro) que se descartan si no son de la guacamaya
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4
      const [r, g, b, al] = [data[i], data[i + 1], data[i + 2], data[i + 3]]
      const d = Math.hypot(r - 1, g - 41, b - 104) // distancia al azul del fondo del logo
      let a = al < 255 && (y < H - 3 || d < 140) ? 0 : Math.max(0, Math.min(1, (d - 45) / 35)) * al
      if (a > 0 && d < 200) {
        outer: for (let dy = -EDGE; dy <= EDGE; dy++) {
          for (let dx = -EDGE; dx <= EDGE; dx++) {
            if (y + dy < H && !opaque(x + dx, y + dy)) {
              a = 0
              break outer
            }
          }
        }
      }
      out[i + 3] = Math.round(a)
    }
  }
  return sharp(out, { raw: { width: W, height: H, channels: 4 } }).png().toBuffer()
})()
const gradient = (size) =>
  Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">` +
      `<stop offset="0" stop-color="${ICON_TOP}"/><stop offset="1" stop-color="${ICON_BOTTOM}"/></linearGradient></defs>` +
      `<rect width="100%" height="100%" fill="url(#g)"/></svg>`,
  )
// La guacamaya a `ratio` del ancho, centrada y apoyada en el borde de abajo (sin sus 1,5 % inferiores,
// que el logo deja medio transparentes)
async function parrotLayer(size, ratio) {
  const w = Math.round(size * ratio)
  const { data, info } = await sharp(parrot).resize({ width: w, kernel: 'lanczos3' }).toBuffer({ resolveWithObject: true })
  const h = info.height - Math.round(info.height * 0.015)
  const input = await sharp(data).extract({ left: 0, top: 0, width: info.width, height: h }).toBuffer()
  return { input, left: Math.round((size - w) / 2), top: size - h }
}
const iconOn = async (size, ratio) =>
  sharp(gradient(size)).composite([await parrotLayer(size, ratio)]).flatten({ background: ICON_TOP }).png()

// iOS / App Store / Play Store (y el ícono de Android antiguo, sin capas)
await (await iconOn(1024, 0.86)).toFile(`${OUT}/icon-only.png`)

// Ícono adaptable de Android: fondo azul + guacamaya. El XML dibuja la capa en la zona visible y la máscara
// más estricta es un círculo: al 84 % la cresta y las plumas de los lados caben enteras
await sharp(gradient(1024)).png().toFile(`${OUT}/icon-background.png`)
await square(1024, { r: 0, g: 0, b: 0, alpha: 0 })
  .composite([await parrotLayer(1024, 0.84)])
  .png()
  .toFile(`${OUT}/icon-foreground.png`)

// Íconos de la web instalable (manifest.webmanifest) y del acceso directo de iPhone
const PUB = `${root}public/icons`
await mkdir(PUB, { recursive: true })
await (await iconOn(192, 0.86)).toFile(`${PUB}/icon-192.png`)
await (await iconOn(512, 0.86)).toFile(`${PUB}/icon-512.png`)
await (await iconOn(512, 0.84)).toFile(`${PUB}/icon-maskable-512.png`) // "maskable": Android recorta hasta un círculo
await (await iconOn(180, 0.86)).toFile(`${PUB}/apple-touch-icon.png`)

// Pantalla de inicio: el logo pequeño en el centro (los sistemas recortan los bordes según la pantalla)
const splash = await square(2732, SPLASH_BG)
  .composite([{ input: await fit(640), gravity: 'center' }])
  .png()
  .toBuffer()
await sharp(splash).toFile(`${OUT}/splash.png`)
await sharp(splash).toFile(`${OUT}/splash-dark.png`)

// Ícono de la ficha de Google Play (512×512, sin transparencia). El de App Store (1024) es icon-only.png.
await sharp(`${OUT}/icon-only.png`).resize(512, 512, { kernel: 'lanczos3' }).png().toFile(`${OUT}/play-store-icon-512.png`)

console.log('Listo: frontend/assets (icon-only, icon-foreground, icon-background, splash, splash-dark, play-store-icon-512)')

// Ícono de notificación de Android: silueta blanca sobre transparente (Android la pinta de un solo color).
// Se separa la guacamaya del fondo azul del logo por distancia de color.
{
  const { data, info } = await sharp(trimmed).resize(192, 192).ensureAlpha().raw().toBuffer({ resolveWithObject: true })
  const out = Buffer.alloc(info.width * info.height * 4)
  for (let i = 0; i < info.width * info.height; i++) {
    const [r, g, b, a] = [data[i * 4], data[i * 4 + 1], data[i * 4 + 2], data[i * 4 + 3]]
    const fondo = Math.hypot(r - 1, g - 41, b - 106) < 70 // azul del logo
    out.set([255, 255, 255, a > 128 && !fondo ? 255 : 0], i * 4)
  }
  // Mediana sobre la máscara: quita los puntitos sueltos del degradado del fondo y tapa huecos pequeños
  const mask = await sharp(out, { raw: { width: info.width, height: info.height, channels: 4 } })
    .extractChannel(3).median(7).threshold(128).png().toBuffer()
  const silueta = await sharp({ create: { width: info.width, height: info.height, channels: 3, background: '#ffffff' } })
    .joinChannel(mask).png().toBuffer()
  const RES = `${root}android/app/src/main/res`
  for (const [dpi, px] of [['mdpi', 24], ['hdpi', 36], ['xhdpi', 48], ['xxhdpi', 72], ['xxxhdpi', 96]]) {
    await mkdir(`${RES}/drawable-${dpi}`, { recursive: true })
    const inner = Math.round(px * 0.92)
    await sharp({ create: { width: px, height: px, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
      .composite([{ input: await sharp(silueta).resize(inner, inner, { kernel: 'lanczos3' }).toBuffer(), gravity: 'center' }])
      .png()
      .toFile(`${RES}/drawable-${dpi}/ic_stat_guako.png`)
  }
  // La misma silueta es el "badge" de la notificación de la web instalada (barra de estado de Android)
  await sharp(`${RES}/drawable-xxxhdpi/ic_stat_guako.png`).toFile(`${root}public/icons/badge-96.png`)
  console.log('Listo: ic_stat_guako (ícono de notificación de Android) y public/icons/badge-96.png')
}
