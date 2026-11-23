// Módulo de comunicación: todas las llamadas al servidor de la Raspberry Pi
export const PUERTO = 5000;

export const urlBase = (ip) => `http://${ip}:${PUERTO}`;

async function pedir(url, opciones = {}, tiempoMs = 4000) {
  const control = new AbortController();
  const timer = setTimeout(() => control.abort(), tiempoMs);
  try {
    const r = await fetch(url, { ...opciones, signal: control.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

export const probarConexion = (ip) => pedir(`${urlBase(ip)}/`, {}, 3000);

export const obtenerEstado = (ip) => pedir(`${urlBase(ip)}/api/estado`);

export const obtenerEventos = (ip, limite = 30) =>
  pedir(`${urlBase(ip)}/api/eventos?limite=${limite}`);

export const cambiarArmado = (ip, armado) =>
  pedir(`${urlBase(ip)}/api/armado`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ armado }),
  });

export const borrarEvento = (ip, archivo) =>
  pedir(`${urlBase(ip)}/api/eventos/${encodeURIComponent(archivo)}`, { method: 'DELETE' });

// Limpia lo que escriba el usuario: "http://192.168.1.50:5000/" -> "192.168.1.50"
export const limpiarIP = (texto) =>
  texto.trim().replace(/^https?:\/\//, '').replace(/:\d+.*$/, '').replace(/\/.*$/, '');
