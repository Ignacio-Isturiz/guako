// Crea la llave de subida (upload key) de Google Play y el archivo android/keystore.properties que la usa.
//
//   npm run android:keystore
//
// Pide la contraseña en la terminal (no se muestra ni se guarda en el historial). La llave queda FUERA del
// repositorio, en ~/.guako/guako-upload.jks. Haz una copia de la llave y de la contraseña en un lugar seguro
// (gestor de contraseñas): con "Play App Signing" Google guarda la llave final, y si pierdes esta se puede
// pedir un reinicio, pero tarda días.
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const KEY_DIR = join(homedir(), '.guako')
const KEY_FILE = join(KEY_DIR, 'guako-upload.jks')
const ALIAS = 'guako-upload'
const PROPS = fileURLToPath(new URL('../android/keystore.properties', import.meta.url))

if (existsSync(KEY_FILE)) {
  console.error(`Ya existe ${KEY_FILE}. No la sobrescribo: bórrala a mano solo si de verdad quieres otra.`)
  process.exit(1)
}

// Lee una línea sin mostrar lo que se escribe
function askHidden(question) {
  return new Promise((resolve) => {
    const { stdin, stdout } = process
    stdout.write(question)
    let value = ''
    stdin.setRawMode(true)
    stdin.resume()
    stdin.setEncoding('utf8')
    const onData = (ch) => {
      if (ch === '\r' || ch === '\n') {
        stdin.setRawMode(false)
        stdin.pause()
        stdin.off('data', onData)
        stdout.write('\n')
        resolve(value)
      } else if (ch === '\u0003') {
        process.exit(130)
      } else if (ch === '\u007f' || ch === '\b') {
        value = value.slice(0, -1)
      } else {
        value += ch
      }
    }
    stdin.on('data', onData)
  })
}

const password = await askHidden('Contraseña para la llave (mínimo 6 caracteres): ')
if (password.length < 6) throw new Error('La contraseña debe tener al menos 6 caracteres')
if ((await askHidden('Repítela: ')) !== password) throw new Error('Las contraseñas no coinciden')

await mkdir(KEY_DIR, { recursive: true })
const keytool = spawnSync(
  'keytool',
  [
    '-genkeypair', '-v',
    '-keystore', KEY_FILE,
    '-alias', ALIAS,
    '-keyalg', 'RSA', '-keysize', '2048',
    '-validity', '10000',
    '-storepass:env', 'GUAKO_KS_PASS',
    '-keypass:env', 'GUAKO_KS_PASS',
    '-dname', 'CN=Guako, O=Guako, C=CO',
  ],
  { stdio: 'inherit', env: { ...process.env, GUAKO_KS_PASS: password } }, // por variable: no aparece en la línea de comandos
)
if (keytool.status !== 0) throw new Error('keytool falló (¿está Java instalado y en el PATH?)')

const forward = (p) => p.replaceAll('\\', '/')
await writeFile(
  PROPS,
  `# Firma de subida a Google Play. NO se sube a git (android/.gitignore).\n` +
    `storeFile=${forward(KEY_FILE)}\nstorePassword=${password}\nkeyAlias=${ALIAS}\nkeyPassword=${password}\n`,
)
console.log(`\nListo:\n  llave:   ${KEY_FILE}\n  config:  ${PROPS}\nGuarda una copia de la llave y de la contraseña en tu gestor de contraseñas.`)
console.log('Siguiente paso: npm run android:bundle  → android/app/build/outputs/bundle/release/app-release.aab')
