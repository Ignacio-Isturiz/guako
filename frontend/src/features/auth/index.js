// Módulo de autenticación: API pública.
// Otros módulos importan SOLO desde este archivo, nunca desde sus archivos internos.
import { addMessages } from '@/core/i18n.js'
import es from './i18n/es.js'
import en from './i18n/en.js'

addMessages({ es, en })

export { getSession, clearSession, logout, MOCK } from './service.js'
export { initAuth, openAuth } from './components/auth-modal/auth-modal.js'
