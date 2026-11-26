// Dirección del backend para todas las llamadas a /api.
//
// VITE_API_URL vacía = mismo origen: en desarrollo Vite redirige /api al backend y en Vercel
// lo reenvía vercel.json. La app móvil (Capacitor) se sirve desde capacitor://localhost o
// https://localhost, así que ahí VITE_API_URL tiene que ser la URL completa del backend
// (ver frontend/.env.example y el script build:mobile de package.json).
export const API_BASE = import.meta.env.VITE_API_URL ?? ''

// apiUrl('/api/users/me') → 'https://…/api/users/me' (o '/api/users/me' en la web)
export const apiUrl = (path) => `${API_BASE}${path}`
