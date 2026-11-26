// Módulo legal (Términos y Política de privacidad): API pública.
// Otros módulos importan SOLO desde este archivo.
import { addMessages } from '@/core/i18n.js'
import { LEGAL_CONFIG } from './content.js'
import es from './i18n/es.js'
import en from './i18n/en.js'

addMessages({ es, en })

export { initLegal, openLegal } from './components/legal-modal/legal-modal.js'

// Versión vigente de los documentos: el registro y la aceptación de cambios la envían al backend.
export const LEGAL_VERSION = LEGAL_CONFIG.version
