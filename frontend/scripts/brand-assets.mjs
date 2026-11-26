// Genera las imágenes base de la app móvil a partir del logo (src/shared/assets/brand/guako-logo.png):
//   assets/icon-only.png        1024×1024 sin transparencia (iOS, App Store, Play Store 512 se saca de aquí)
//   assets/icon-foreground.png  1024×1024 capa delantera del ícono adaptable de Android (dentro de la zona segura)
//   assets/icon-background.png  1024×1024 capa de fondo (azul del logo)
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
const LOGO_BG = '#01296a' // azul del fondo del logo (medido en sus píxeles)
const SPLASH_BG = '#0b2a6b' // --navy de tokens.css, el mismo de capacitor.config.json

// El logo sin el margen transparente que lo rodea
const trimmed = await sharp(LOGO).trim({ threshold: 0 }).toBuffer()
const square = (size, background) => sharp({ create: { width: size, height: size, channels: 4, background } })
const fit = (size) => sharp(trimmed).resize(size, size, { fit: 'cover', kernel: 'lanczos3' }).toBuffer()

await mkdir(OUT, { recursive: true })

// Ícono completo: el logo llena el cuadrado y sus esquinas redondeadas quedan del mismo azul (cada sistema
// le pone su propia máscara: círculo, cuadrado redondeado…)
await square(1024, LOGO_BG)
  .composite([{ input: await fit(1024) }])
  .flatten({ background: LOGO_BG })
  .png()
  .toFile(`${OUT}/icon-only.png`)

// Ícono adaptable de Android: la máscara recorta hasta un 33 %, así que el dibujo va al 70 % y centrado
const fg = Math.round(1024 * 0.7)
await square(1024, { r: 0, g: 0, b: 0, alpha: 0 })
  .composite([{ input: await fit(fg), gravity: 'center' }])
  .png()
  .toFile(`${OUT}/icon-foreground.png`)
await square(1024, LOGO_BG).png().toFile(`${OUT}/icon-background.png`)

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
  console.log('Listo: ic_stat_guako (ícono de notificación de Android)')
}
