// Idioma de la interfaz (ES / EN).
// Cada módulo registra sus propios textos con `addMessages()` desde su index.js,
// así los diccionarios viven junto al código que los usa.
const DICTS = { es: {}, en: {} }
const KEY = 'guako.lang'

let lang = 'es'
try {
  const saved = localStorage.getItem(KEY)
  if (saved && saved in DICTS) lang = saved
} catch {
  /* sin almacenamiento: se queda en español */
}
document.documentElement.lang = lang

// addMessages({ es, en }) mezcla las claves de primer nivel de cada idioma.
// Para agrupar bajo un prefijo: addMessages({ es, en }, 'app') → t('app.home.title')
export function addMessages(dicts, namespace = '') {
  for (const code of Object.keys(DICTS)) {
    const add = dicts[code] || {}
    if (namespace) DICTS[code][namespace] = { ...DICTS[code][namespace], ...add }
    else Object.assign(DICTS[code], add)
  }
}

const dig = (dict, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), dict)

export const getLang = () => lang

// t('hero.lead')  ·  t('hero.lead')  ·  también devuelve listas y objetos
export function t(path, params) {
  let v = dig(DICTS[lang], path)
  if (v === undefined) v = dig(DICTS.es, path)
  if (typeof v === 'string' && params) v = v.replace(/\{(\w+)\}/g, (m, k) => (params[k] ?? m))
  return v === undefined ? path : v
}

export function applyMeta() {
  document.documentElement.lang = lang
  document.title = t('meta.title')
  document.querySelector('meta[name="description"]')?.setAttribute('content', t('meta.description'))
}

export function setLang(next) {
  if (!(next in DICTS) || next === lang) return
  lang = next
  try {
    localStorage.setItem(KEY, lang)
  } catch {
    /* sin almacenamiento */
  }
  applyMeta()
  window.dispatchEvent(new CustomEvent('langchange', { detail: lang }))
}
