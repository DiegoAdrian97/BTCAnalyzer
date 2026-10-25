/*
 * El analisis corre aca, en segundo plano, para que la pantalla no se trabe mientras calcula.
 * Repite cada INTERVALO ms mientras la app esta a la vista; se pausa cuando no.
 */
importScripts('indicadores.js', 'aprendizaje.js', 'analisis.js', 'datos.js');

const INTERVALO = 12000;
let pausado = false, corriendo = false, timer = null, numero = 0;

async function ciclo() {
  if (corriendo) return;
  corriendo = true;
  clearTimeout(timer);
  const t0 = Date.now();
  try {
    const input = await Datos.recolectar((texto) => postMessage({ tipo: 'progreso', texto }));
    const { rows, log } = Analisis.analizar(input);
    Datos.guardarLog(log);
    numero += 1;
    postMessage({ tipo: 'analisis', rows, numero, ms: Date.now() - t0, fuente: input.fuente });
  } catch (e) {
    postMessage({ tipo: 'error', texto: e && e.message ? e.message : String(e) });
  }
  corriendo = false;
  if (!pausado) timer = setTimeout(ciclo, Math.max(2000, INTERVALO - (Date.now() - t0)));
}

onmessage = (ev) => {
  if (ev.data.tipo === 'pausa') {
    pausado = true;
    clearTimeout(timer);
  } else if (ev.data.tipo === 'seguir') {
    pausado = false;
    ciclo();
  }
};

ciclo();
