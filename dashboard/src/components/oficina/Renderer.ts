// Renderizador isométrico de la oficina en Canvas 2D.
// Sin dependencias: un solo bucle rAF, orden por profundidad y dibujo vectorial
// (nada de assets). Dimensionado para ~40 objetos animados a 60 fps.

import type { AgenteOficina, DeptoOficina, OficinaData } from "@/lib/oficina";
import {
  TILE_H,
  TILE_W,
  camaraCentradaEn,
  limitarZoom,
  mundoAPantalla,
  pantallaAMundo,
  zoomEnPunto,
  type Camara,
} from "./iso";

interface SeleccionCallbacks {
  onDepto: (id: string | null) => void;
  onAgente: (agente: AgenteOficina | null) => void;
  /** Abre (true) o cierra (false) el panel de la Wall. */
  onWall: (sel: boolean) => void;
}

const ATRIO = { x: -3.5, y: -3.5, w: 7, h: 7.5 }; // zona central despejada
const WALL = { x: -8, y: -9.6, w: 16, anchoPx: 520, altoPx: 190 }; // pantalla norte

export class OficinaRenderer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private datos: OficinaData;
  private cb: SeleccionCallbacks;
  private cam: Camara;
  private raf = 0;
  private t = 0;
  private ultimo = 0;
  private dpr = 1;
  private ancho = 0;
  private alto = 0;

  private deptoSel: string | null = null;
  private agenteSel: AgenteOficina | null = null;
  private hoverDepto: string | null = null;
  private hoverAgente: AgenteOficina | null = null;
  private hoverWall = false;

  private arrastrando = false;
  private punteroPrev = { x: 0, y: 0 };
  private movio = false;
  private pinchPrev: number | null = null;
  private punteros = new Map<number, { x: number; y: number }>();

  private foco: { wx: number; wy: number; zoom?: number } | null = null; // animación de cámara
  private centroInicial = false;

  constructor(canvas: HTMLCanvasElement, datos: OficinaData, cb: SeleccionCallbacks) {
    this.canvas = canvas;
    this.datos = datos;
    this.cb = cb;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("Canvas 2D no disponible");
    this.ctx = ctx;
    this.cam = camaraCentradaEn(0, -1, canvas.clientWidth || 1280, canvas.clientHeight || 720, 0.8);
    this.observar();
    this.ultimo = performance.now();
    this.raf = requestAnimationFrame(this.loop);
  }

  // -------------------------------------------------------------------------
  // API pública
  // -------------------------------------------------------------------------

  redimensionar(ancho: number, alto: number, dpr: number) {
    this.ancho = ancho;
    this.alto = alto;
    this.dpr = Math.min(dpr, 2);
    this.canvas.width = Math.round(ancho * this.dpr);
    this.canvas.height = Math.round(alto * this.dpr);
    // Primera medición real: centrar la escena (el constructor puede correr
    // antes de que el canvas tenga layout).
    if (!this.centroInicial && ancho > 0 && alto > 0) {
      this.cam = camaraCentradaEn(0, -1, ancho, alto, 0.8);
      this.centroInicial = true;
    }
  }

  seleccionarDepto(id: string | null) {
    this.deptoSel = id;
    if (id) this.agenteSel = null;
  }

  seleccionarAgente(agente: AgenteOficina | null) {
    this.agenteSel = agente;
    if (agente) this.deptoSel = null;
  }

  /** Anima la cámara hasta el centro de la sala. */
  enfocarDepto(id: string) {
    const d = this.datos.departamentos.find((x) => x.id === id);
    if (d) this.foco = { wx: d.x + d.w / 2, wy: d.y + d.h / 2 };
  }

  resetCamara() {
    this.foco = { wx: 0, wy: -1, zoom: 0.8 };
  }

  /** Enfoca la Wall sin cambiar el zoom. */
  enfocarWall() {
    this.foco = { wx: 0, wy: -6.4 };
  }

  destruir() {
    cancelAnimationFrame(this.raf);
    const c = this.canvas;
    c.removeEventListener("pointerdown", this.onDown);
    c.removeEventListener("pointermove", this.onMove);
    window.removeEventListener("pointerup", this.onUp);
    window.removeEventListener("pointercancel", this.onCancel);
    c.removeEventListener("wheel", this.onWheel);
    c.removeEventListener("pointerleave", this.onLeave);
  }

  /** Sustituye los datos (tick de simulación / regeneración) sin perder cámara ni selección. */
  actualizarDatos(datos: OficinaData) {
    this.datos = datos;
  }

  // -------------------------------------------------------------------------
  // Entrada
  // -------------------------------------------------------------------------

  private observar() {
    const c = this.canvas;
    c.addEventListener("pointerdown", this.onDown);
    c.addEventListener("pointermove", this.onMove);
    window.addEventListener("pointerup", this.onUp);
    window.addEventListener("pointercancel", this.onCancel);
    c.addEventListener("wheel", this.onWheel, { passive: false });
    c.addEventListener("pointerleave", this.onLeave);
  }

  private pos(e: { clientX: number; clientY: number }) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private onDown = (e: PointerEvent) => {
    this.canvas.setPointerCapture(e.pointerId);
    this.punteros.set(e.pointerId, this.pos(e));
    if (this.punteros.size === 2) this.pinchPrev = null;
    this.arrastrando = true;
    this.movio = false;
    this.punteroPrev = this.pos(e);
    this.foco = null;
  };

  private onMove = (e: PointerEvent) => {
    const p = this.pos(e);
    if (this.arrastrando && this.punteros.has(e.pointerId)) this.punteros.set(e.pointerId, p);

    // Pellizco en táctil
    if (this.punteros.size === 2) {
      const [a, b] = [...this.punteros.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (this.pinchPrev !== null) {
        const centro = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        this.cam = zoomEnPunto(this.cam, dist / this.pinchPrev, centro.x, centro.y);
      }
      this.pinchPrev = dist;
      return;
    }

    if (this.arrastrando) {
      const dx = p.x - this.punteroPrev.x;
      const dy = p.y - this.punteroPrev.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) this.movio = true;
      this.cam.x += dx;
      this.cam.y += dy;
      this.punteroPrev = p;
      return;
    }

    // Hover
    const hitA = this.agenteEn(p.x, p.y);
    this.hoverAgente = hitA;
    this.hoverWall = !hitA && this.enWall(p.x, p.y);
    this.hoverDepto = hitA || this.hoverWall ? null : this.deptoEn(p.x, p.y);
    this.canvas.style.cursor = hitA || this.hoverDepto || this.hoverWall ? "pointer" : "grab";
  };

  private onLeave = () => {
    this.hoverDepto = null;
    this.hoverAgente = null;
    this.hoverWall = false;
  };

  private onCancel = (e: PointerEvent) => {
    this.punteros.delete(e.pointerId);
    if (this.punteros.size < 2) this.pinchPrev = null;
    if (this.punteros.size === 0) {
      this.arrastrando = false;
      this.movio = false;
    }
  };

  private onUp = (e: PointerEvent) => {
    // Un gesto (pellizco a dos dedos) nunca termina en selección.
    const eraGesto = this.punteros.size > 1;
    this.punteros.delete(e.pointerId);
    if (this.punteros.size < 2) this.pinchPrev = null;
    if (!this.arrastrando) return;
    this.arrastrando = false;
    if (this.movio || eraGesto) return;

    // Clic: agente primero, luego wall, luego sala
    const p = this.pos(e);
    const agente = this.agenteEn(p.x, p.y);
    if (agente) {
      this.seleccionarAgente(agente);
      this.cb.onAgente(agente);
      this.cb.onDepto(null);
      this.cb.onWall(false);
      return;
    }
    if (this.enWall(p.x, p.y)) {
      this.cb.onAgente(null);
      this.cb.onDepto(null);
      this.cb.onWall(true);
      return;
    }
    const depto = this.deptoEn(p.x, p.y);
    this.seleccionarDepto(depto);
    this.cb.onAgente(null);
    this.cb.onWall(false);
    if (depto) {
      this.enfocarDepto(depto);
      this.cb.onDepto(depto);
    } else {
      this.cb.onDepto(null);
    }
  };

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    const p = this.pos(e);
    this.cam = zoomEnPunto(this.cam, e.deltaY < 0 ? 1.12 : 1 / 1.12, p.x, p.y);
    this.foco = null;
  };

  // -------------------------------------------------------------------------
  // Hit-testing
  // -------------------------------------------------------------------------

  private agenteEn(sx: number, sy: number): AgenteOficina | null {
    let mejor: AgenteOficina | null = null;
    let dMejor = Infinity;
    for (const d of this.datos.departamentos) {
      for (const a of d.agentes) {
        const { sx: ax, sy: ay } = mundoAPantalla(a.x, a.y, this.cam);
        // Centro del cuerpo (cabeza + torso), con margen holgado para el dedo/cursor.
        const dist = Math.hypot(sx - ax, sy - (ay - 16 * this.cam.zoom));
        if (dist < 24 * this.cam.zoom && dist < dMejor) {
          mejor = a;
          dMejor = dist;
        }
      }
    }
    return mejor;
  }

  private deptoEn(sx: number, sy: number): string | null {
    const { wx, wy } = pantallaAMundo(sx, sy, this.cam);
    for (const d of this.datos.departamentos) {
      if (wx >= d.x && wx <= d.x + d.w && wy >= d.y && wy <= d.y + d.h) return d.id;
    }
    return null;
  }

  /** Rectángulo en pantalla que ocupa la Wall. */
  private rectWall(): { x: number; y: number; w: number; h: number } {
    const z = this.cam.zoom;
    const ancla = mundoAPantalla(WALL.x, WALL.y, this.cam);
    return { x: ancla.sx - (WALL.anchoPx * z) / 2, y: ancla.sy - WALL.altoPx * z, w: WALL.anchoPx * z, h: WALL.altoPx * z };
  }

  private enWall(sx: number, sy: number): boolean {
    const r = this.rectWall();
    return sx >= r.x && sx <= r.x + r.w && sy >= r.y && sy <= r.y + r.h;
  }

  // -------------------------------------------------------------------------
  // Bucle
  // -------------------------------------------------------------------------

  private loop = (t: number) => {
    this.raf = requestAnimationFrame(this.loop);
    if (document.hidden) {
      this.ultimo = t;
      return;
    }
    const dt = Math.min((t - this.ultimo) / 1000, 0.1);
    this.ultimo = t;
    this.t += dt;

    if (this.foco) {
      // Viaje suave de la cámara hacia el foco
      const zoomDestino = this.foco.zoom ?? this.cam.zoom;
      const destino = camaraCentradaEn(this.foco.wx, this.foco.wy, this.ancho, this.alto, zoomDestino);
      const k = 1 - Math.pow(0.0015, dt); // easing exponencial
      this.cam.x += (destino.x - this.cam.x) * k;
      this.cam.y += (destino.y - this.cam.y) * k;
      this.cam.zoom += (zoomDestino - this.cam.zoom) * k;
      if (
        Math.abs(destino.x - this.cam.x) < 0.5 &&
        Math.abs(zoomDestino - this.cam.zoom) < 0.005
      )
        this.foco = null;
    }

    this.dibujar();
  };

  // -------------------------------------------------------------------------
  // Dibujo
  // -------------------------------------------------------------------------

  private dibujar() {
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    // Fondo
    const g = ctx.createLinearGradient(0, 0, 0, this.alto);
    g.addColorStop(0, "#080d18");
    g.addColorStop(1, "#05070d");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, this.ancho, this.alto);

    this.dibujarRejilla();
    this.dibujarWall();
    this.dibujarSuelos();
    this.dibujarObjetos();
    this.dibujarEtiquetas();
  }

  private dibujarRejilla() {
    const ctx = this.ctx;
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(56,120,190,0.10)";
    const paso = 2;
    for (let x = -18; x <= 18; x += paso) {
      const a = mundoAPantalla(x, -11, this.cam);
      const b = mundoAPantalla(x, 12, this.cam);
      ctx.beginPath();
      ctx.moveTo(a.sx, a.sy);
      ctx.lineTo(b.sx, b.sy);
      ctx.stroke();
    }
    for (let y = -11; y <= 12; y += paso) {
      const a = mundoAPantalla(-18, y, this.cam);
      const b = mundoAPantalla(18, y, this.cam);
      ctx.beginPath();
      ctx.moveTo(a.sx, a.sy);
      ctx.lineTo(b.sx, b.sy);
      ctx.stroke();
    }
  }

  /** Diamante isométrico de un rectángulo del mundo. */
  private rombo(x: number, y: number, w: number, h: number): { sx: number; sy: number }[] {
    return [
      mundoAPantalla(x, y, this.cam),
      mundoAPantalla(x + w, y, this.cam),
      mundoAPantalla(x + w, y + h, this.cam),
      mundoAPantalla(x, y + h, this.cam),
    ];
  }

  private poligono(puntos: { sx: number; sy: number }[], fill: string, stroke?: string) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.moveTo(puntos[0].sx, puntos[0].sy);
    for (let i = 1; i < puntos.length; i++) ctx.lineTo(puntos[i].sx, puntos[i].sy);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  private dibujarSuelos() {
    const ctx = this.ctx;

    // Atrio con logo
    const atrio = this.rombo(ATRIO.x, ATRIO.y, ATRIO.w, ATRIO.h);
    this.poligono(atrio, "rgba(52,211,153,0.05)", "rgba(52,211,153,0.25)");
    const centro = mundoAPantalla(0, 1.2, this.cam);
    ctx.save();
    ctx.translate(centro.sx, centro.sy);
    ctx.scale(this.cam.zoom, this.cam.zoom);
    ctx.fillStyle = "rgba(52,211,153,0.16)";
    ctx.font = "700 22px ui-sans-serif, system-ui";
    ctx.textAlign = "center";
    ctx.fillText("TRADING FLOOR", 0, 0);
    ctx.restore();

    for (const d of this.datos.departamentos) {
      const sel = this.deptoSel === d.id;
      const hov = this.hoverDepto === d.id;
      const pts = this.rombo(d.x, d.y, d.w, d.h);
      const color = d.color;

      // Suelo de la sala
      const base = this.hexARgba(color, sel ? 0.16 : hov ? 0.13 : 0.08);
      this.poligono(pts, base, this.hexARgba(color, sel ? 0.9 : hov ? 0.6 : 0.35));

      // Resplandor de selección
      if (sel) {
        ctx.save();
        ctx.shadowColor = this.hexARgba(color, 0.8);
        ctx.shadowBlur = 18;
        this.poligono(pts, "rgba(0,0,0,0)", this.hexARgba(color, 0.9));
        ctx.restore();
      }

      // Borde "pared" norte de la sala (altitud)
      const a = mundoAPantalla(d.x, d.y, this.cam);
      const b = mundoAPantalla(d.x + d.w, d.y, this.cam);
      const altura = 26 * this.cam.zoom;
      ctx.beginPath();
      ctx.moveTo(a.sx, a.sy);
      ctx.lineTo(b.sx, b.sy);
      ctx.lineTo(b.sx, b.sy - altura);
      ctx.lineTo(a.sx, a.sy - altura);
      ctx.closePath();
      ctx.fillStyle = this.hexARgba(color, 0.10);
      ctx.fill();
      ctx.strokeStyle = this.hexARgba(color, 0.4);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  private dibujarObjetos() {
    // Orden por profundidad (x + y)
    type Dibujable = { profundidad: number; fn: () => void };
    const lista: Dibujable[] = [];

    for (const d of this.datos.departamentos) {
      // Mesa por agente + agente
      for (const a of d.agentes) {
        lista.push({ profundidad: a.x + a.y - 0.4, fn: () => this.dibujarMesa(d, a) });
        lista.push({ profundidad: a.x + a.y, fn: () => this.dibujarAgente(d, a) });
      }
      // Planta decorativa en la esquina sur de cada sala
      lista.push({
        profundidad: d.x + d.y + d.h - 0.3,
        fn: () => this.dibujarPlanta(d.x + d.w - 0.7, d.y + d.h - 0.7),
      });
    }
    lista.sort((p, q) => p.profundidad - q.profundidad);
    for (const item of lista) item.fn();
  }

  private dibujarMesa(d: DeptoOficina, a: AgenteOficina) {
    const ctx = this.ctx;
    const p = mundoAPantalla(a.x, a.y + 0.35, this.cam);
    const z = this.cam.zoom;
    const w = 46 * z;
    const h = 23 * z;

    // Tablero de la mesa (prisma isométrico)
    this.poligono(
      [
        { sx: p.sx, sy: p.sy - h / 2 },
        { sx: p.sx + w / 2, sy: p.sy },
        { sx: p.sx, sy: p.sy + h / 2 },
        { sx: p.sx - w / 2, sy: p.sy },
      ],
      "#16213a",
      "rgba(148,163,184,0.35)",
    );

    // Monitor
    const mon = { x: p.sx, y: p.sy - h / 2 - 16 * z };
    ctx.fillStyle = "#0b1120";
    ctx.fillRect(mon.x - 13 * z, mon.y - 15 * z, 26 * z, 18 * z);
    ctx.strokeStyle = this.hexARgba(d.color, 0.8);
    ctx.lineWidth = 1.2;
    ctx.strokeRect(mon.x - 13 * z, mon.y - 15 * z, 26 * z, 18 * z);
    // Resplandor de pantalla
    ctx.save();
    ctx.shadowColor = this.hexARgba(d.color, 0.9);
    ctx.shadowBlur = 8;
    ctx.fillStyle = this.hexARgba(d.color, 0.35);
    ctx.fillRect(mon.x - 11 * z, mon.y - 13 * z, 22 * z, 14 * z);
    ctx.restore();
    // Pie del monitor
    ctx.strokeStyle = "rgba(148,163,184,0.5)";
    ctx.beginPath();
    ctx.moveTo(mon.x, mon.y + 3 * z);
    ctx.lineTo(mon.x, mon.y + 8 * z);
    ctx.stroke();
  }

  private dibujarAgente(d: DeptoOficina, a: AgenteOficina) {
    const ctx = this.ctx;
    const z = this.cam.zoom;
    const p = mundoAPantalla(a.x, a.y, this.cam);
    const trabajando = a.estado === "trabajando";
    const alerta = a.estado === "alerta";
    const bob = trabajando ? Math.sin(this.t * 3.2 + a.fase) * 1.6 * z : Math.sin(this.t * 1.1 + a.fase) * 0.6 * z;
    const selAgente = this.agenteSel?.id === a.id;
    const hov = this.hoverAgente?.id === a.id;

    // Sombra
    ctx.beginPath();
    ctx.ellipse(p.sx, p.sy + 2 * z, 11 * z, 5 * z, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fill();

    // Cuerpo (cápsula con el color del departamento)
    const cuerpoY = p.sy - 16 * z + bob;
    ctx.beginPath();
    ctx.roundRect(p.sx - 8 * z, cuerpoY - 8 * z, 16 * z, 22 * z, 8 * z);
    ctx.fillStyle = this.hexARgba(d.color, 0.85);
    ctx.fill();

    // Cabeza
    const cabezaY = cuerpoY - 14 * z;
    ctx.beginPath();
    ctx.arc(p.sx, cabezaY, 7 * z, 0, Math.PI * 2);
    ctx.fillStyle = "#f4d3b3";
    ctx.fill();
    // Auriculares
    ctx.strokeStyle = "#1e293b";
    ctx.lineWidth = 2 * z;
    ctx.beginPath();
    ctx.arc(p.sx, cabezaY, 8.4 * z, Math.PI * 1.08, Math.PI * 1.92);
    ctx.stroke();

    // Anillo de estado
    if (alerta) {
      const pulso = 10 + Math.sin(this.t * 5) * 2.5;
      ctx.beginPath();
      ctx.arc(p.sx, cabezaY - 13 * z, pulso * z, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(248,113,113,0.9)";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(p.sx, cabezaY - 13 * z, 4.4 * z, 0, Math.PI * 2);
      ctx.fillStyle = "#f87171";
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.arc(p.sx, cabezaY - 13 * z, 4.4 * z, 0, Math.PI * 2);
      ctx.fillStyle = trabajando ? "#38bdf8" : "#34d399";
      ctx.fill();
      if (selAgente || hov) {
        ctx.strokeStyle = this.hexARgba(trabajando ? "#38bdf8" : "#34d399", 0.7);
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.arc(p.sx, cabezaY - 13 * z, 7.5 * z, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    // Burbuja de tarea al hacer hover o selección
    if ((selAgente || hov) && !this.agenteSel) {
      const texto = a.tarea.length > 42 ? `${a.tarea.slice(0, 42)}…` : a.tarea;
      ctx.font = `${11}px ui-sans-serif, system-ui`;
      const w = ctx.measureText(texto).width + 16;
      const bx = p.sx - w / 2;
      const by = cabezaY - 46 * z;
      ctx.beginPath();
      ctx.roundRect(bx, by, w, 24, 8);
      ctx.fillStyle = "rgba(8,12,22,0.92)";
      ctx.fill();
      ctx.strokeStyle = this.hexARgba(d.color, 0.6);
      ctx.stroke();
      ctx.fillStyle = "#e2e8f0";
      ctx.textAlign = "center";
      ctx.fillText(texto, p.sx, by + 16);
    }
  }

  private dibujarPlanta(x: number, y: number) {
    const ctx = this.ctx;
    const p = mundoAPantalla(x, y, this.cam);
    const z = this.cam.zoom;
    ctx.fillStyle = "#14532d";
    ctx.fillRect(p.sx - 5 * z, p.sy - 8 * z, 10 * z, 8 * z);
    ctx.beginPath();
    ctx.arc(p.sx, p.sy - 12 * z, 7 * z, 0, Math.PI * 2);
    ctx.arc(p.sx - 5 * z, p.sy - 9 * z, 5 * z, 0, Math.PI * 2);
    ctx.arc(p.sx + 5 * z, p.sy - 9 * z, 5 * z, 0, Math.PI * 2);
    ctx.fillStyle = "#16a34a";
    ctx.fill();
  }

  /** La Wall: pantalla norte con las métricas clave. */
  private dibujarWall() {
    const ctx = this.ctx;
    const z = this.cam.zoom;
    const ancla = mundoAPantalla(WALL.x, WALL.y, this.cam);
    const w = WALL.anchoPx * z;
    const h = WALL.altoPx * z;
    const x = ancla.sx - w / 2;
    const y = ancla.sy - h;

    // Marco (se ilumina al pasar el cursor)
    ctx.fillStyle = "#0b1120";
    ctx.beginPath();
    ctx.roundRect(x - 10 * z, y - 10 * z, w + 20 * z, h + 20 * z, 10 * z);
    ctx.fill();
    ctx.strokeStyle = this.hoverWall ? "rgba(52,211,153,0.65)" : "rgba(148,163,184,0.3)";
    ctx.stroke();

    // Pantalla
    const grad = ctx.createLinearGradient(x, y, x, y + h);
    grad.addColorStop(0, "#0a1a14");
    grad.addColorStop(1, "#071011");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, 6 * z);
    ctx.fill();

    // Título y modo
    ctx.textAlign = "left";
    ctx.fillStyle = "#34d399";
    ctx.font = `700 ${15 * z}px ui-sans-serif, system-ui`;
    ctx.fillText("TRADING FLOOR — MEMORIA OPERATIVA", x + 18 * z, y + 26 * z);

    const modo = this.datos.kpis.modo;
    const modoColor = modo === "LIVE" ? "#f87171" : modo === "PAPER" ? "#fbbf24" : "#38bdf8";
    ctx.font = `600 ${11 * z}px ui-sans-serif, system-ui`;
    const tw = ctx.measureText(modo).width + 14 * z;
    ctx.fillStyle = "rgba(0,0,0,0.4)";
    ctx.beginPath();
    ctx.roundRect(x + w - tw - 18 * z, y + 12 * z, tw, 18 * z, 9 * z);
    ctx.fill();
    ctx.strokeStyle = modoColor;
    ctx.stroke();
    ctx.fillStyle = modoColor;
    ctx.fillText(modo, x + w - tw - 11 * z, y + 25 * z);

    // Tarjetas de métricas
    const k = this.datos.kpis;
    const tarjetas = [
      { et: "P&L HOY", val: `${k.pnlDia >= 0 ? "+" : ""}${k.pnlDia.toFixed(0)} €`, color: k.pnlDia >= 0 ? "#34d399" : "#f87171" },
      { et: "P&L ACUM", val: `${k.pnlAcumulado >= 0 ? "+" : ""}${k.pnlAcumulado.toFixed(0)} €`, color: k.pnlAcumulado >= 0 ? "#34d399" : "#f87171" },
      { et: "EXPOSICIÓN", val: `${k.exposicionPct.toFixed(1)} %`, color: k.exposicionPct > 60 ? "#fbbf24" : "#e2e8f0", barra: k.exposicionPct / 100 },
      { et: "PRESUPUESTO", val: `${k.presupuestoUsadoPct.toFixed(0)} %`, color: k.presupuestoUsadoPct > 80 ? "#fbbf24" : "#e2e8f0", barra: k.presupuestoUsadoPct / 100 },
      { et: "VIVAS", val: String(k.estrategiasVivas), color: "#e2e8f0" },
    ];
    const cw = (w - 36 * z) / tarjetas.length;
    tarjetas.forEach((tj, i) => {
      const cx = x + 18 * z + i * cw;
      const cy = y + 40 * z;
      const ch = 74 * z;
      ctx.fillStyle = "rgba(255,255,255,0.03)";
      ctx.beginPath();
      ctx.roundRect(cx, cy, cw - 10 * z, ch, 6 * z);
      ctx.fill();
      ctx.fillStyle = "rgba(148,163,184,0.8)";
      ctx.font = `500 ${9.5 * z}px ui-sans-serif, system-ui`;
      ctx.fillText(tj.et, cx + 8 * z, cy + 16 * z);
      ctx.fillStyle = tj.color;
      ctx.font = `700 ${17 * z}px ui-sans-serif, system-ui`;
      ctx.fillText(tj.val, cx + 8 * z, cy + 40 * z);
      if (tj.barra !== undefined) {
        ctx.fillStyle = "rgba(255,255,255,0.08)";
        ctx.fillRect(cx + 8 * z, cy + 52 * z, cw - 26 * z, 5 * z);
        ctx.fillStyle = tj.color;
        ctx.fillRect(cx + 8 * z, cy + 52 * z, (cw - 26 * z) * Math.min(tj.barra, 1), 5 * z);
      }
    });

    // Sparkline de equity
    const eq = this.datos.equity;
    if (eq.length > 1) {
      const sx0 = x + 18 * z;
      const sy0 = y + h - 46 * z;
      const sw = w - 36 * z;
      const sh = 28 * z;
      const vs = eq.map((p) => p.equity);
      const vmin = Math.min(...vs);
      const vmax = Math.max(...vs);
      ctx.strokeStyle = "#34d399";
      ctx.lineWidth = 1.6 * z;
      ctx.beginPath();
      eq.forEach((p, i) => {
        const px = sx0 + (i / (eq.length - 1)) * sw;
        const py = sy0 + sh - ((p.equity - vmin) / (vmax - vmin || 1)) * sh;
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.stroke();
      ctx.fillStyle = "rgba(148,163,184,0.7)";
      ctx.font = `${9 * z}px ui-sans-serif, system-ui`;
      ctx.fillText("EQUITY (PAPEL, 30 D)", sx0, sy0 + sh + 12 * z);
    }

    // Barrido de escaneo
    const scanY = y + ((this.t * 40) % h);
    const sg = ctx.createLinearGradient(x, scanY - 8 * z, x, scanY + 8 * z);
    sg.addColorStop(0, "rgba(52,211,153,0)");
    sg.addColorStop(0.5, "rgba(52,211,153,0.06)");
    sg.addColorStop(1, "rgba(52,211,153,0)");
    ctx.fillStyle = sg;
    ctx.fillRect(x, scanY - 8 * z, w, 16 * z);

    // Soporte
    ctx.strokeStyle = "rgba(148,163,184,0.35)";
    ctx.lineWidth = 3 * z;
    ctx.beginPath();
    ctx.moveTo(ancla.sx - 60 * z, y + h + 8 * z);
    ctx.lineTo(ancla.sx - 40 * z, ancla.sy + 6 * z);
    ctx.moveTo(ancla.sx + 60 * z, y + h + 8 * z);
    ctx.lineTo(ancla.sx + 40 * z, ancla.sy + 6 * z);
    ctx.stroke();
  }

  private dibujarEtiquetas() {
    const ctx = this.ctx;
    ctx.textAlign = "center";
    for (const d of this.datos.departamentos) {
      const p = mundoAPantalla(d.x + d.w / 2, d.y + d.h - 0.35, this.cam);
      const texto = d.nombre.toUpperCase();
      ctx.font = `600 ${11 * this.cam.zoom}px ui-sans-serif, system-ui`;
      const tw = ctx.measureText(texto).width;
      const dim = this.deptoSel && this.deptoSel !== d.id;
      ctx.fillStyle = "rgba(5,8,14,0.75)";
      ctx.beginPath();
      ctx.roundRect(p.sx - tw / 2 - 8, p.sy - 10 * this.cam.zoom, tw + 16, 18 * this.cam.zoom, 9);
      ctx.fill();
      ctx.fillStyle = dim ? "rgba(148,163,184,0.5)" : d.color;
      ctx.fillText(texto, p.sx, p.sy + 4 * this.cam.zoom);
    }
  }

  private hexARgba(hex: string, alpha: number): string {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
  }
}
