// Módulo legal (Términos y Política de privacidad): API pública.
// Otros módulos importan SOLO desde este archivo.
import { addMessages } from '@/core/i18n.js'
import es from './i18n/es.js'
import en from './i18n/en.js'

addMessages({ es, en })

export { initLegal, openLegal } from './components/legal-modal/legal-modal.js'
