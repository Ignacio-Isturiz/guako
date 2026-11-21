// Ilustraciones compartidas por la landing y la app (papel recortado + risografía).
// Para añadir una: guarda roles/<nombre>.webp y úsala con roleArt('<nombre>').
// Si el archivo no existe devuelve undefined, para que cada pieza decida su marcador provisional.
const ROLES = import.meta.glob('./roles/*.webp', { eager: true, query: '?url', import: 'default' })

export const roleArt = (name) => ROLES[`./roles/${name}.webp`]
