// Sube la versión de la app móvil en Android e iOS a la vez (cada envío a una tienda necesita una nueva).
//
//   npm run version:mobile               → 1.0.0 pasa a 1.0.1 y el número de compilación sube en 1
//   npm run version:mobile -- minor      → 1.0.1 pasa a 1.1.0
//   npm run version:mobile -- major      → 1.1.0 pasa a 2.0.0
//   npm run version:mobile -- 1.4.2      → versión exacta
//
// Toca: android/app/build.gradle (versionCode, versionName) e ios/App/App.xcodeproj/project.pbxproj
// (CURRENT_PROJECT_VERSION, MARKETING_VERSION, que Info.plist ya lee). El número de compilación es el mismo
// en las dos plataformas y nunca baja: las tiendas rechazan uno repetido.
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const GRADLE = `${root}android/app/build.gradle`
const PBXPROJ = `${root}ios/App/App.xcodeproj/project.pbxproj`

const gradle = await readFile(GRADLE, 'utf8')
const pbx = await readFile(PBXPROJ, 'utf8')

const currentName = gradle.match(/versionName "([^"]+)"/)?.[1]
const androidCode = Number(gradle.match(/versionCode (\d+)/)?.[1])
const iosCode = Math.max(...[...pbx.matchAll(/CURRENT_PROJECT_VERSION = (\d+);/g)].map((m) => Number(m[1])))
if (!currentName || !androidCode || !Number.isFinite(iosCode)) throw new Error('No encontré la versión actual')

const [major = 0, minor = 0, patch = 0] = currentName.split('.').map(Number)
const wanted = process.argv[2] ?? 'patch'
const name = /^\d+\.\d+\.\d+$/.test(wanted)
  ? wanted
  : { major: `${major + 1}.0.0`, minor: `${major}.${minor + 1}.0`, patch: `${major}.${minor}.${patch + 1}` }[wanted]
if (!name) throw new Error(`Uso: patch | minor | major | X.Y.Z (recibí "${wanted}")`)
const code = Math.max(androidCode, iosCode) + 1

await writeFile(
  GRADLE,
  gradle.replace(/versionCode \d+/, `versionCode ${code}`).replace(/versionName "[^"]+"/, `versionName "${name}"`),
)
await writeFile(
  PBXPROJ,
  pbx
    .replace(/CURRENT_PROJECT_VERSION = \d+;/g, `CURRENT_PROJECT_VERSION = ${code};`)
    .replace(/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${name};`),
)
console.log(`Versión ${currentName} → ${name} · compilación ${code} (Android e iOS)`)
