// Borrador de la conversación que se está preparando (tema y nivel).
// Lo escribe Preparar y lo lee Conversación; vive en sessionStorage (se borra al cerrar la pestaña).
const KEY = 'guako.setup'
export const readSetup = () => {
  try {
    return JSON.parse(sessionStorage.getItem(KEY))
  } catch {
    return null
  }
}
export const writeSetup = (s) => {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* sin almacenamiento */
  }
}
export const clearSetup = () => {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* sin almacenamiento */
  }
}
