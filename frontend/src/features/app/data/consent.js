// Preferencia "Guardar mi audio" (consentimiento para medir la pronunciación).
// Viene ACTIVADA por defecto y se cambia en Ajustes; solo un "0" guardado la apaga. Se recuerda por
// cuenta en este navegador. Si no hay almacenamiento no se puede recordar una elección, así que en
// ese caso se queda apagada (lo seguro: el backend descarta el audio tras transcribirlo).
import { getSession } from '@/features/auth/index.js'

const keyOf = () => `guako.audioConsent.${getSession()?.email || 'anon'}`

export const readAudioConsent = () => {
  try {
    return localStorage.getItem(keyOf()) !== '0'
  } catch {
    return false
  }
}

export const writeAudioConsent = (on) => {
  try {
    localStorage.setItem(keyOf(), on ? '1' : '0')
  } catch {
    /* sin almacenamiento */
  }
}
