import { matchPath } from '@/core/router.js'

// Rutas de la aplicación. La landing vive en "/" y la app en "/app/...".
// `name` es también la carpeta de la pantalla en views/ (views/<name>/<name>.js).
export const ROUTES = [
  { name: 'inicio', path: '/app/inicio' },
  { name: 'preparar', path: '/app/preparar' },
  { name: 'conversacion', path: '/app/conversacion', focus: true }, // pantalla completa, sin menú
  { name: 'informe', path: '/app/informe/:id' },
  { name: 'revision', path: '/app/revision/:id' },
  { name: 'progreso', path: '/app/progreso' },
  { name: 'conversaciones', path: '/app/conversaciones' },
  { name: 'practica', path: '/app/practica' },
  { name: 'ajustes', path: '/app/ajustes' },
]

export const isAppPath = (p = location.pathname) => p === '/app' || p.startsWith('/app/')

export function matchRoute(pathname = location.pathname) {
  for (const route of ROUTES) {
    const params = matchPath(route.path, pathname)
    if (params) return { route, params }
  }
  return null
}
