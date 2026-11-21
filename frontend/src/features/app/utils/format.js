import { t, getLang } from '@/core/i18n.js'

// Fechas, saludos y nombres en el idioma de la interfaz
const locale = () => (getLang() === 'en' ? 'en-US' : 'es-CO')
export const fmtDate = (iso, opts = { day: 'numeric', month: 'short' }) => new Intl.DateTimeFormat(locale(), opts).format(new Date(iso))
export const fmtLong = (iso) => new Intl.DateTimeFormat(locale(), { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(iso))
export const fmtWeekday = (d) => new Intl.DateTimeFormat(locale(), { weekday: 'narrow' }).format(d)

export const topicName = (c) => (c.topicId === 'custom' && c.topicLabel ? c.topicLabel : t(`app.topics.${c.topicId}.name`))

export const greeting = () => {
  const h = new Date().getHours()
  return t(h < 12 ? 'app.greet.morning' : h < 19 ? 'app.greet.afternoon' : 'app.greet.evening')
}
export const firstName = (name = '') => name.trim().split(/\s+/)[0] || ''
