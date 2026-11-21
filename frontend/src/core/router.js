// Navegación sin recargar la página (History API).
// Quien quiera reaccionar a un cambio de URL escucha el evento `routechange`.

export function navigate(path, { replace = false } = {}) {
  if (path !== location.pathname + location.search) {
    history[replace ? 'replaceState' : 'pushState'](null, '', path)
  }
  window.dispatchEvent(new CustomEvent('routechange'))
}

// Compara una ruta con un patrón tipo "/app/informe/:id" y devuelve sus parámetros (o null)
export function matchPath(pattern, pathname = location.pathname) {
  const clean = pathname.replace(/\/+$/, '') || '/'
  const a = pattern.split('/')
  const b = clean.split('/')
  if (a.length !== b.length) return null
  const params = {}
  const ok = a.every((seg, i) => {
    if (seg.startsWith(':')) {
      params[seg.slice(1)] = decodeURIComponent(b[i])
      return true
    }
    return seg === b[i]
  })
  return ok ? params : null
}

window.addEventListener('popstate', () => window.dispatchEvent(new CustomEvent('routechange')))
