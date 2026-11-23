// Configuración de la app que viene de variables de entorno de Vite (ver frontend/.env.example).
import { MOCK } from '@/features/auth/index.js'

// Base de la API. Vacía = mismo origen (en desarrollo, Vite redirige /api al backend).
export const API_BASE = import.meta.env.VITE_API_URL ?? ''

// Modo demo: la conversación y el informe usan datos de ejemplo del navegador, sin backend.
// Con la sesión de demo (VITE_AUTH_MOCK) no existe cookie real, así que también cuenta como demo.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true' || MOCK
