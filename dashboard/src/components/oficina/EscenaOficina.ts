// Escena isométrica low-poly de la oficina en Three.js.
// Orthographic camera 2:1, materiales facetados, salas de cristal y backdrop
// urbano. Sustituye al Renderer Canvas 2D manteniendo la API pública.

import * as THREE from "three";
import type { AgenteOficina, DeptoOficina, OficinaData } from "@/lib/oficina";

export interface CallbacksEscena {
  onDepto: (id: string | null) => void;
  onAgente: (agente: AgenteOficina | null) => void;
  onWall: (sel: boolean) => void;
}

interface Cam {
  objetivo: THREE.Vector3;
  zoom: number;
}

/** Elevación para proyección 2:1 (dimétrica de videojuego). */
const ELEV = Math.atan(0.5);
const AZIM = Math.PI / 4;
const DIST_CAM = 48;

const COLOR_LIENZO = 0x060a13;
const COLOR_SUELO = 0x0a1220;
const COLOR_MURO = 0x1b2740;

const ESTADO_SALA: Record<DeptoOficina["estado"], { borde: number; intensidad: number }> = {
  operativo: { borde: 0x34d399, intensidad: 0.55 },
  ocupado: { borde: 0x38bdf8, intensidad: 0.5 },
  degradado: { borde: 0xfbbf24, intensidad: 0.65 },
  pausado: { borde: 0x64748b, intensidad: 0.25 },
};

const hexAInt = (hex: string) => parseInt(hex.slice(1), 16);

function materialFacetado(color: number, opacidad = 1): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color,
    flatShading: true,
    roughness: 0.82,
    metalness: 0.08,
    transparent: opacidad < 1,
    opacity: opacidad,
  });
}

function crearTexto(texto: string, color: string, { w = 512, h = 96, font = "700 48px ui-sans-serif, system-ui" } = {}): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  ctx.clearRect(0, 0, w, h);
  ctx.font = font;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "rgba(5,8,14,0.82)";
  const tw = ctx.measureText(texto).width + 36;
  ctx.beginPath();
  ctx.roundRect((w - tw) / 2, h / 2 - 28, tw, 56, 14);
  ctx.fill();
  ctx.strokeStyle = `${color}66`;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fillText(texto, w / 2, h / 2 + 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

function crearSprite(texto: string, color: string, escala = 1.8): THREE.Sprite {
  const mat = new THREE.SpriteMaterial({
    map: crearTexto(texto, color),
    transparent: true,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(escala * 3.2, escala * 0.6, 1);
  return sprite;
}

export class EscenaOficina {
  private canvas: HTMLCanvasElement;
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camara: THREE.OrthographicCamera;
  private cam: Cam;
  private datos: OficinaData;
  private cb: CallbacksEscena;

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

  private foco: { objetivo: THREE.Vector3; zoom?: number } | null = null;
  private centroInicial = false;

  private raycaster = new THREE.Raycaster();
  private punteroNdc = new THREE.Vector2();

  private meshesDepto = new Map<string, THREE.Object3D>();
  private meshesAgente = new Map<string, THREE.Group>();
  private meshesWall: THREE.Object3D[] = [];
  private materiales: THREE.Material[] = [];
  private agentesAnim: { grupo: THREE.Group; fase: number; estado: AgenteOficina["estado"]; yBase: number }[] = [];
  private lucesMonitores: THREE.PointLight[] = [];
  private texturaWall: THREE.CanvasTexture | null = null;
  private wallMesh: THREE.Mesh | null = null;
  private etiquetasDepto = new Map<string, THREE.Sprite>();
  private spriteWall: THREE.Sprite | null = null;

  private contenedorAgentes = new THREE.Group();
  private contenedorSuelo = new THREE.Group();
  private contenedorCristal = new THREE.Group();
  private contenedorFondo = new THREE.Group();

  constructor(canvas: HTMLCanvasElement, datos: OficinaData, cb: CallbacksEscena) {
    this.canvas = canvas;
    this.datos = datos;
    this.cb = cb;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(COLOR_LIENZO);
    this.scene.fog = new THREE.Fog(COLOR_LIENZO, 34, 72);

    const izq = -22;
    const der = 22;
    const arr = 16;
    const aba = -16;
    this.camara = new THREE.OrthographicCamera(izq, der, arr, aba, 0.1, 200);
    this.cam = { objetivo: new THREE.Vector3(0, 0, -0.5), zoom: 0.92 };

    this.construirLuces();
    this.scene.add(this.contenedorFondo, this.contenedorSuelo, this.contenedorCristal, this.contenedorAgentes);
    this.construirFondo();
    this.construirSueloBase();
    this.reconstruir(datos);

    this.aplicarCamara(canvas.clientWidth || 1280, canvas.clientHeight || 720);
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
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(ancho, alto, false);
    if (!this.centroInicial && ancho > 0 && alto > 0) {
      this.cam.objetivo.set(0, 0, -0.5);
      this.cam.zoom = 0.92;
      this.centroInicial = true;
    }
    this.aplicarCamara(ancho, alto);
  }

  seleccionarDepto(id: string | null) {
    this.deptoSel = id;
    if (id) this.agenteSel = null;
    this.refrescarResaltado();
  }

  seleccionarAgente(agente: AgenteOficina | null) {
    this.agenteSel = agente;
    if (agente) this.deptoSel = null;
    this.refrescarResaltado();
  }

  enfocarDepto(id: string) {
    const d = this.datos.departamentos.find((x) => x.id === id);
    if (!d) return;
    this.foco = {
      objetivo: new THREE.Vector3(d.x + d.w / 2, 0, d.y + d.h / 2),
      zoom: 1.45,
    };
  }

  resetCamara() {
    this.foco = { objetivo: new THREE.Vector3(0, 0, -0.5), zoom: 0.92 };
  }

  enfocarWall() {
    this.foco = { objetivo: new THREE.Vector3(0, 0, -7.2), zoom: 1.25 };
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

    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else if (mat) mat.dispose();
    });
    this.materiales.forEach((m) => m.dispose());
    this.texturaWall?.dispose();
    this.renderer.dispose();
  }

  actualizarDatos(datos: OficinaData) {
    const deptosPrev = this.datos.departamentos;
    const agentesPrev = new Map(deptosPrev.flatMap((d) => d.agentes).map((a) => [a.id, a]));
    this.datos = datos;

    // Reconstrucción ligera: posiciones/estados; la geometría se reutiliza si el layout coincide.
    const layoutClave = datos.departamentos.map((d) => `${d.id}:${d.x},${d.y},${d.w},${d.h},${d.color}`).join("|");
    const prevClave = deptosPrev.map((d) => `${d.id}:${d.x},${d.y},${d.w},${d.h},${d.color}`).join("|");
    if (layoutClave !== prevClave || this.meshesDepto.size === 0) {
      this.reconstruir(datos);
    } else {
      this.actualizarAgentes(datos, agentesPrev);
      this.actualizarWallTextura();
      this.refrescarResaltado();
    }
  }

  // -------------------------------------------------------------------------
  // Construcción de escena
  // -------------------------------------------------------------------------

  private construirLuces() {
    const ambient = new THREE.AmbientLight(0x6a7f9c, 0.55);
    this.scene.add(ambient);

    const hemi = new THREE.HemisphereLight(0x9ec5ff, 0x0a0f1a, 0.35);
    this.scene.add(hemi);

    const dir = new THREE.DirectionalLight(0xdde8ff, 1.15);
    dir.position.set(18, 28, 12);
    dir.castShadow = true;
    dir.shadow.mapSize.set(1024, 1024);
    dir.shadow.camera.near = 1;
    dir.shadow.camera.far = 80;
    dir.shadow.camera.left = -30;
    dir.shadow.camera.right = 30;
    dir.shadow.camera.top = 30;
    dir.shadow.camera.bottom = -30;
    dir.shadow.bias = -0.0008;
    this.scene.add(dir);

    const relleno = new THREE.DirectionalLight(0x34d399, 0.18);
    relleno.position.set(-14, 10, -8);
    this.scene.add(relleno);
  }

  private construirFondo() {
    // Suelo profundo bajo la oficina
    const baseGeo = new THREE.BoxGeometry(80, 0.4, 60);
    const baseMat = materialFacetado(COLOR_SUELO);
    this.materiales.push(baseMat);
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.set(0, -0.3, 0);
    base.receiveShadow = true;
    this.contenedorFondo.add(base);

    // Skyline low-poly tras la wall (y negativa = norte en pantalla)
    const rng = mulberry32(20261006);
    for (let i = 0; i < 56; i++) {
      const w = 1.4 + rng() * 2.8;
      const d = 1.4 + rng() * 2.6;
      const h = 4 + rng() * 18;
      const x = -40 + rng() * 80;
      const z = -13 - rng() * 26;
      const tono = 0x243550 + Math.floor(rng() * 0x181818);
      const mat = materialFacetado(tono, 0.7 + rng() * 0.25);
      this.materiales.push(mat);
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(x, h / 2 - 0.2, z);
      this.contenedorFondo.add(m);

      // Ventanas emisivas
      const winMat = new THREE.MeshBasicMaterial({
        color: rng() > 0.65 ? 0x34d399 : rng() > 0.35 ? 0x38bdf8 : 0xfbbf24,
        transparent: true,
        opacity: 0.18 + rng() * 0.22,
      });
      this.materiales.push(winMat);
      const win = new THREE.Mesh(new THREE.BoxGeometry(w * 0.75, h * 0.72, 0.06), winMat);
      win.position.set(x, h / 2 - 0.2, z + d / 2 + 0.04);
      this.contenedorFondo.add(win);
    }

    // Ventanal / marco decorativo al norte
    const marcoMat = new THREE.MeshStandardMaterial({
      color: 0x2a3b5c,
      flatShading: true,
      roughness: 0.55,
      metalness: 0.35,
      transparent: true,
      opacity: 0.4,
      emissive: 0x1a3050,
      emissiveIntensity: 0.25,
    });
    this.materiales.push(marcoMat);
    const marco = new THREE.Mesh(new THREE.BoxGeometry(48, 18, 0.25), marcoMat);
    marco.position.set(0, 8, -13.2);
    this.contenedorFondo.add(marco);

    // Brillo de ciudad en el horizonte
    const brillo = new THREE.Mesh(
      new THREE.PlaneGeometry(60, 16),
      new THREE.MeshBasicMaterial({ color: 0x0e2a3d, transparent: true, opacity: 0.45 }),
    );
    brillo.position.set(0, 6, -14);
    this.contenedorFondo.add(brillo);
  }

  private construirSueloBase() {
    // Rejilla isométrica sutil
    const grid = new THREE.GridHelper(48, 24, 0x1b3a5c, 0x14243a);
    grid.position.y = 0.01;
    const gridMat = grid.material as THREE.Material;
    if (Array.isArray(gridMat)) {
      gridMat.forEach((m) => {
        m.transparent = true;
        (m as THREE.Material & { opacity: number }).opacity = 0.35;
      });
    } else {
      gridMat.transparent = true;
      (gridMat as THREE.Material & { opacity: number }).opacity = 0.35;
    }
    grid.userData.base = true;
    this.contenedorSuelo.add(grid);

    // Atrio central
    const atrioGeo = new THREE.BoxGeometry(7, 0.08, 7.5);
    const atrioMat = new THREE.MeshStandardMaterial({
      color: 0x0d2a22,
      flatShading: true,
      roughness: 0.7,
      metalness: 0.15,
      emissive: 0x34d399,
      emissiveIntensity: 0.08,
    });
    this.materiales.push(atrioMat);
    const atrio = new THREE.Mesh(atrioGeo, atrioMat);
    atrio.position.set(0, 0.05, 0.25);
    atrio.receiveShadow = true;
    atrio.userData.base = true;
    this.contenedorSuelo.add(atrio);

    const logo = crearSprite("TRADING FLOOR", "#34d399", 2.4);
    logo.position.set(0, 1.4, 0.25);
    logo.userData.base = true;
    this.contenedorSuelo.add(logo);
  }

  private reconstruir(datos: OficinaData) {
    this.vaciarGrupo(this.contenedorSuelo);
    this.vaciarGrupo(this.contenedorCristal);
    this.vaciarGrupo(this.contenedorAgentes);
    this.meshesDepto.clear();
    this.meshesAgente.clear();
    this.meshesWall = [];
    this.agentesAnim = [];
    this.lucesMonitores = [];
    this.etiquetasDepto.clear();
    this.spriteWall = null;
    this.wallMesh = null;

    this.construirSueloBase();
    for (const d of datos.departamentos) this.construirSala(d);
    this.construirWall(datos);
    this.actualizarWallTextura();
    this.refrescarResaltado();
  }

  private vaciarGrupo(g: THREE.Group) {
    const hijos = [...g.children];
    for (const h of hijos) g.remove(h);
  }

  private construirSala(d: DeptoOficina) {
    const color = hexAInt(d.color);
    const estado = ESTADO_SALA[d.estado];
    const cx = d.x + d.w / 2;
    const cz = d.y + d.h / 2;
    const grupo = new THREE.Group();
    grupo.userData.deptoId = d.id;

    // Suelo de la sala
    const sueloGeo = new THREE.BoxGeometry(d.w, 0.12, d.h);
    const sueloMat = materialFacetado(color, 0.28);
    sueloMat.emissive = new THREE.Color(color);
    sueloMat.emissiveIntensity = 0.08;
    this.materiales.push(sueloMat);
    const suelo = new THREE.Mesh(sueloGeo, sueloMat);
    suelo.position.set(cx, 0.06, cz);
    suelo.receiveShadow = true;
    suelo.userData.deptoId = d.id;
    grupo.add(suelo);

    // Muros de cristal (bajos, con arista emisiva)
    const altoMuro = 1.85;
    const cristalMat = new THREE.MeshPhysicalMaterial({
      color,
      transparent: true,
      opacity: 0.16,
      roughness: 0.12,
      metalness: 0.08,
      transmission: 0.65,
      thickness: 0.35,
      side: THREE.DoubleSide,
      flatShading: true,
    });
    this.materiales.push(cristalMat);

    const aristaMat = new THREE.MeshStandardMaterial({
      color: estado.borde,
      emissive: estado.borde,
      emissiveIntensity: estado.intensidad * 0.7,
      flatShading: true,
      roughness: 0.4,
      metalness: 0.4,
    });
    this.materiales.push(aristaMat);

    const muros: { x: number; z: number; w: number; d: number }[] = [
      { x: cx, z: d.y, w: d.w, d: 0.1 }, // norte
      { x: cx, z: d.y + d.h, w: d.w, d: 0.1 }, // sur
      { x: d.x, z: cz, w: 0.1, d: d.h }, // oeste
      { x: d.x + d.w, z: cz, w: 0.1, d: d.h }, // este
    ];
    for (const m of muros) {
      const geo = new THREE.BoxGeometry(m.w, altoMuro, m.d);
      const mesh = new THREE.Mesh(geo, cristalMat);
      mesh.position.set(m.x, altoMuro / 2, m.z);
      mesh.userData.deptoId = d.id;
      grupo.add(mesh);

      const arista = new THREE.Mesh(new THREE.BoxGeometry(m.w + 0.06, 0.07, m.d + 0.06), aristaMat);
      arista.position.set(m.x, altoMuro + 0.04, m.z);
      grupo.add(arista);
    }

    // Mesas de la plantilla + densificación visual (puestos vacíos low-poly)
    for (const a of d.agentes) {
      this.construirPuesto(grupo, d, a);
    }
    this.densificarSala(grupo, d);

    // Planta decorativa
    this.construirPlanta(grupo, d.x + d.w - 0.7, d.y + d.h - 0.7);

    // Etiqueta flotante
    const etiqueta = crearSprite(d.nombre.toUpperCase(), d.color, 1.5);
    etiqueta.position.set(cx, 2.9, cz);
    etiqueta.userData.deptoId = d.id;
    grupo.add(etiqueta);
    this.etiquetasDepto.set(d.id, etiqueta);

    // Badge de agentes
    const badge = crearSprite(`${d.agentes.length}`, "#e2e8f0", 0.7);
    badge.position.set(cx + d.w * 0.3, 2.9, cz);
    grupo.add(badge);

    this.meshesDepto.set(d.id, grupo);
    this.contenedorCristal.add(grupo);
  }

  /** Añade mesas/monitores decorativos para que la sala parezca poblada. */
  private densificarSala(grupo: THREE.Group, d: DeptoOficina) {
    const filas = d.h >= 3.8 ? 2 : 1;
    const porFila = Math.max(2, Math.floor(d.w / 2.4));
    const ocupados = new Set(d.agentes.map((a) => `${a.x.toFixed(1)}|${a.y.toFixed(1)}`));
    const color = hexAInt(d.color);
    const mesaMat = materialFacetado(0x16213a);
    const pantallaMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.45 });
    this.materiales.push(mesaMat, pantallaMat);

    let creadas = 0;
    for (let f = 0; f < filas && creadas < 10; f++) {
      for (let i = 0; i < porFila && creadas < 10; i++) {
        const x = d.x + 1.2 + i * 2.1;
        const y = d.y + 1.1 + f * (d.h - 1.8);
        if (x > d.x + d.w - 1.0 || y > d.y + d.h - 0.9) continue;
        if (ocupados.has(`${x.toFixed(1)}|${y.toFixed(1)}`)) continue;
        // Evitar solapes con puestos reales (radio holgado)
        let cerca = false;
        for (const a of d.agentes) {
          if (Math.hypot(a.x - x, a.y - y) < 1.1) {
            cerca = true;
            break;
          }
        }
        if (cerca) continue;

        const mesa = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.08, 0.65), mesaMat);
        mesa.position.set(x, 0.42, y + 0.2);
        mesa.castShadow = true;
        mesa.receiveShadow = true;
        mesa.userData.deptoId = d.id;
        grupo.add(mesa);

        const mon = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.32, 0.05), materialFacetado(0x0b1120));
        mon.position.set(x, 0.76, y);
        mon.userData.deptoId = d.id;
        grupo.add(mon);

        const pantalla = new THREE.Mesh(new THREE.PlaneGeometry(0.44, 0.26), pantallaMat);
        pantalla.position.set(x, 0.76, y - 0.03);
        pantalla.rotation.y = Math.PI;
        grupo.add(pantalla);
        creadas++;
      }
    }
  }

  private construirPuesto(grupo: THREE.Group, d: DeptoOficina, a: AgenteOficina) {
    // Mesa
    const mesaGeo = new THREE.BoxGeometry(1.1, 0.08, 0.7);
    const mesaMat = materialFacetado(0x16213a);
    this.materiales.push(mesaMat);
    const mesa = new THREE.Mesh(mesaGeo, mesaMat);
    mesa.position.set(a.x, 0.42, a.y + 0.25);
    mesa.castShadow = true;
    mesa.receiveShadow = true;
    mesa.userData.agenteId = a.id;
    mesa.userData.deptoId = d.id;
    grupo.add(mesa);

    // Patas
    const pataMat = materialFacetado(0x0f172a);
    this.materiales.push(pataMat);
    for (const [px, pz] of [
      [-0.45, -0.25],
      [0.45, -0.25],
      [-0.45, 0.25],
      [0.45, 0.25],
    ] as const) {
      const pata = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.42, 0.06), pataMat);
      pata.position.set(a.x + px, 0.21, a.y + 0.25 + pz);
      grupo.add(pata);
    }

    // Monitor con pantalla emisiva
    const color = hexAInt(d.color);
    const monitor = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.36, 0.06), materialFacetado(0x0b1120));
    monitor.position.set(a.x, 0.8, a.y + 0.05);
    monitor.userData.agenteId = a.id;
    monitor.userData.deptoId = d.id;
    grupo.add(monitor);

    const pantallaMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 });
    this.materiales.push(pantallaMat);
    const pantalla = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 0.29), pantallaMat);
    pantalla.position.set(a.x, 0.8, a.y + 0.015);
    pantalla.rotation.y = Math.PI;
    grupo.add(pantalla);

    // Pie
    const pie = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.28, 0.08), pataMat);
    pie.position.set(a.x, 0.56, a.y + 0.05);
    grupo.add(pie);

    // Luz de punto en el monitor
    const luz = new THREE.PointLight(color, 0.55, 3.6, 2);
    luz.position.set(a.x, 1.05, a.y - 0.1);
    grupo.add(luz);
    this.lucesMonitores.push(luz);

    // Agente low-poly (un poco más grande para lectura a distancia)
    const agente = this.crearAgente(d, a);
    agente.grupo.scale.setScalar(1.15);
    grupo.add(agente.grupo);
    this.meshesAgente.set(a.id, agente.grupo);
    this.agentesAnim.push({
      grupo: agente.grupo,
      fase: a.fase,
      estado: a.estado,
      yBase: agente.yBase,
    });
  }

  private crearAgente(d: DeptoOficina, a: AgenteOficina): { grupo: THREE.Group; yBase: number } {
    const color = hexAInt(d.color);
    const g = new THREE.Group();
    g.position.set(a.x, 0, a.y - 0.15);
    g.userData.agenteId = a.id;
    g.userData.deptoId = d.id;

    // Sombra
    const sombra = new THREE.Mesh(
      new THREE.CircleGeometry(0.22, 12),
      new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }),
    );
    sombra.rotation.x = -Math.PI / 2;
    sombra.position.y = 0.02;
    g.add(sombra);

    // Cuerpo (cápsula low-poly)
    const cuerpoMat = materialFacetado(color, 0.95);
    cuerpoMat.emissive = new THREE.Color(color);
    cuerpoMat.emissiveIntensity = 0.22;
    this.materiales.push(cuerpoMat);
    const cuerpo = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.3, 2, 6), cuerpoMat);
    cuerpo.position.y = 0.44;
    cuerpo.castShadow = true;
    cuerpo.userData.agenteId = a.id;
    cuerpo.userData.deptoId = d.id;
    g.add(cuerpo);

    // Cabeza
    const cabezaMat = materialFacetado(0xf0c9a0);
    this.materiales.push(cabezaMat);
    const cabeza = new THREE.Mesh(new THREE.IcosahedronGeometry(0.14, 0), cabezaMat);
    cabeza.position.y = 0.82;
    cabeza.castShadow = true;
    cabeza.userData.agenteId = a.id;
    cabeza.userData.deptoId = d.id;
    g.add(cabeza);

    // Anillo de estado
    const estadoColor = a.estado === "alerta" ? 0xf87171 : a.estado === "trabajando" ? 0x38bdf8 : 0x34d399;
    const anilloMat = new THREE.MeshBasicMaterial({ color: estadoColor, transparent: true, opacity: 0.95 });
    this.materiales.push(anilloMat);
    const anillo = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.022, 6, 16), anilloMat);
    anillo.position.y = 1.08;
    anillo.rotation.x = Math.PI / 2;
    anillo.userData.agenteId = a.id;
    anillo.userData.deptoId = d.id;
    anillo.userData.esAnillo = true;
    g.add(anillo);

    return { grupo: g, yBase: 0 };
  }

  private construirPlanta(grupo: THREE.Group, x: number, y: number) {
    const maceta = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.25, 0.35), materialFacetado(0x3f3f46));
    maceta.position.set(x, 0.12, y);
    grupo.add(maceta);
    const hojas = new THREE.Mesh(new THREE.IcosahedronGeometry(0.28, 0), materialFacetado(0x16a34a));
    hojas.position.set(x, 0.45, y);
    hojas.scale.y = 1.2;
    grupo.add(hojas);
  }

  private construirWall(datos: OficinaData) {
    // Pantalla norte: marco + panel emisivo
    const cx = 0;
    const cz = -9.4;
    const ancho = 16;
    const alto = 4.2;

    const marco = new THREE.Mesh(
      new THREE.BoxGeometry(ancho + 0.6, alto + 0.5, 0.35),
      materialFacetado(0x0b1120),
    );
    marco.position.set(cx, alto / 2 + 0.4, cz - 0.1);
    marco.castShadow = true;
    marco.userData.esWall = true;
    this.contenedorCristal.add(marco);
    this.meshesWall.push(marco);

    // Panel con textura de KPIs
    this.texturaWall = this.crearTexturaWall(datos);
    const panelMat = new THREE.MeshBasicMaterial({ map: this.texturaWall });
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(ancho, alto), panelMat);
    panel.position.set(cx, alto / 2 + 0.4, cz + 0.12);
    panel.userData.esWall = true;
    this.contenedorCristal.add(panel);
    this.meshesWall.push(panel);
    this.wallMesh = panel;

    // Soportes
    const soporteMat = materialFacetado(0x24304d);
    this.materiales.push(soporteMat);
    for (const sx of [-4.5, 4.5]) {
      const s = new THREE.Mesh(new THREE.BoxGeometry(0.35, 1.2, 0.35), soporteMat);
      s.position.set(cx + sx, 0.5, cz - 0.2);
      this.contenedorCristal.add(s);
    }

    // Luz de acento sobre la wall (el título va en la textura del panel)
    const luzWall = new THREE.PointLight(0x34d399, 0.85, 18, 2);
    luzWall.position.set(0, 3.6, -7.4);
    this.contenedorCristal.add(luzWall);
  }

  private crearTexturaWall(datos: OficinaData): THREE.CanvasTexture {
    const w = 1024;
    const h = 268;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d")!;
    this.pintarWall(ctx, w, h, datos);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  private actualizarWallTextura() {
    if (!this.texturaWall) return;
    const c = this.texturaWall.image as HTMLCanvasElement;
    const ctx = c.getContext("2d")!;
    this.pintarWall(ctx, c.width, c.height, this.datos);
    this.texturaWall.needsUpdate = true;
  }

  private pintarWall(ctx: CanvasRenderingContext2D, w: number, h: number, datos: OficinaData) {
    const k = datos.kpis;
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "#0a1a14");
    g.addColorStop(1, "#071011");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // Scanlines sutiles
    ctx.fillStyle = "rgba(52,211,153,0.03)";
    for (let y = 0; y < h; y += 4) ctx.fillRect(0, y, w, 1);

    ctx.fillStyle = "#34d399";
    ctx.font = "700 26px ui-sans-serif, system-ui";
    ctx.fillText("TRADING FLOOR — MEMORIA OPERATIVA", 24, 36);

    const modoColor = k.modo === "LIVE" ? "#f87171" : k.modo === "PAPER" ? "#fbbf24" : "#38bdf8";
    ctx.font = "600 16px ui-sans-serif, system-ui";
    const modo = k.modo;
    const tw = ctx.measureText(modo).width + 20;
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.beginPath();
    ctx.roundRect(w - tw - 20, 14, tw, 28, 14);
    ctx.fill();
    ctx.strokeStyle = modoColor;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = modoColor;
    ctx.fillText(modo, w - tw - 10, 34);

    const tarjetas = [
      { et: "P&L HOY", val: `${k.pnlDia >= 0 ? "+" : ""}${k.pnlDia.toFixed(0)} €`, color: k.pnlDia >= 0 ? "#34d399" : "#f87171", barra: null as number | null },
      { et: "P&L ACUM", val: `${k.pnlAcumulado >= 0 ? "+" : ""}${k.pnlAcumulado.toFixed(0)} €`, color: k.pnlAcumulado >= 0 ? "#34d399" : "#f87171", barra: null },
      { et: "EXPOSICIÓN", val: `${k.exposicionPct.toFixed(1)} %`, color: k.exposicionPct > 60 ? "#fbbf24" : "#e2e8f0", barra: k.exposicionPct / 100 },
      { et: "PRESUPUESTO", val: `${k.presupuestoUsadoPct.toFixed(0)} %`, color: k.presupuestoUsadoPct > 80 ? "#fbbf24" : "#e2e8f0", barra: k.presupuestoUsadoPct / 100 },
      { et: "VIVAS", val: String(k.estrategiasVivas), color: "#e2e8f0", barra: null },
    ];
    const cw = (w - 40) / tarjetas.length;
    tarjetas.forEach((tj, i) => {
      const cx = 20 + i * cw;
      const cy = 52;
      const ch = 78;
      ctx.fillStyle = "rgba(255,255,255,0.04)";
      ctx.beginPath();
      ctx.roundRect(cx, cy, cw - 10, ch, 8);
      ctx.fill();
      ctx.fillStyle = "rgba(148,163,184,0.85)";
      ctx.font = "500 12px ui-sans-serif, system-ui";
      ctx.fillText(tj.et, cx + 12, cy + 22);
      ctx.fillStyle = tj.color;
      ctx.font = "700 24px ui-sans-serif, system-ui";
      ctx.fillText(tj.val, cx + 12, cy + 50);
      if (tj.barra !== null) {
        ctx.fillStyle = "rgba(255,255,255,0.08)";
        ctx.fillRect(cx + 12, cy + 60, cw - 34, 5);
        ctx.fillStyle = tj.color;
        ctx.fillRect(cx + 12, cy + 60, (cw - 34) * Math.min(Math.max(tj.barra, 0), 1), 5);
      }
    });

    // Sparkline equity
    const eq = datos.equity;
    if (eq.length > 1) {
      const sx0 = 20;
      const sy0 = h - 40;
      const sw = w - 40;
      const sh = 52;
      const vs = eq.map((p) => p.equity);
      const vmin = Math.min(...vs);
      const vmax = Math.max(...vs);
      ctx.beginPath();
      eq.forEach((p, i) => {
        const px = sx0 + (i / (eq.length - 1)) * sw;
        const py = sy0 + sh - ((p.equity - vmin) / (vmax - vmin || 1)) * sh;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.strokeStyle = "#34d399";
      ctx.lineWidth = 2.5;
      ctx.stroke();
      ctx.lineTo(sx0 + sw, sy0 + sh);
      ctx.lineTo(sx0, sy0 + sh);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, sy0, 0, sy0 + sh);
      grad.addColorStop(0, "rgba(52,211,153,0.35)");
      grad.addColorStop(1, "rgba(52,211,153,0.02)");
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.fillStyle = "rgba(148,163,184,0.75)";
      ctx.font = "12px ui-sans-serif, system-ui";
      ctx.fillText("EQUITY · 30 D", sx0, sy0 - 6);
    }
  }

  // -------------------------------------------------------------------------
  // Actualizaciones de datos
  // -------------------------------------------------------------------------

  private actualizarAgentes(datos: OficinaData, prev: Map<string, AgenteOficina>) {
    const nuevos = datos.departamentos.flatMap((d) => d.agentes.map((a) => ({ a, d })));
    // Si cambia el número de agentes, reconstruir salas
    if (nuevos.length !== this.agentesAnim.length) {
      this.reconstruir(datos);
      return;
    }
    for (const { a, d } of nuevos) {
      const anim = this.agentesAnim.find((x) => x.grupo.userData.agenteId === a.id);
      if (!anim) continue;
      anim.estado = a.estado;
      // Actualizar anillo de estado
      anim.grupo.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.userData.esAnillo) return;
        const mat = mesh.material as THREE.MeshBasicMaterial;
        mat.color.setHex(a.estado === "alerta" ? 0xf87171 : a.estado === "trabajando" ? 0x38bdf8 : 0x34d399);
      });
      // Si cambió de sala (color), reconstruir
      const prevAg = prev.get(a.id);
      if (prevAg && prevAg.departamento !== d.id) {
        this.reconstruir(datos);
        return;
      }
    }
  }

  // -------------------------------------------------------------------------
  // Cámara
  // -------------------------------------------------------------------------

  private aplicarCamara(ancho: number, alto: number) {
    const aspecto = ancho / Math.max(alto, 1);
    // Ajuste del frustum ortho al aspecto (conserva alto vertical en mundo)
    const baseAlto = 22 / this.cam.zoom;
    const baseAncho = baseAlto * aspecto;
    this.camara.left = -baseAncho / 2;
    this.camara.right = baseAncho / 2;
    this.camara.top = baseAlto / 2;
    this.camara.bottom = -baseAlto / 2;
    this.camara.zoom = 1;
    this.camara.position.set(
      this.cam.objetivo.x + DIST_CAM * Math.cos(ELEV) * Math.sin(AZIM),
      this.cam.objetivo.y + DIST_CAM * Math.sin(ELEV),
      this.cam.objetivo.z + DIST_CAM * Math.cos(ELEV) * Math.cos(AZIM),
    );
    this.camara.lookAt(this.cam.objetivo);
    this.camara.updateProjectionMatrix();
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

    if (this.punteros.size === 2) {
      const [a, b] = [...this.punteros.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (this.pinchPrev !== null && this.pinchPrev > 0) {
        this.cam.zoom = limitarZoom(this.cam.zoom * (dist / this.pinchPrev));
        this.aplicarCamara(this.ancho, this.alto);
      }
      this.pinchPrev = dist;
      return;
    }

    if (this.arrastrando) {
      const dx = p.x - this.punteroPrev.x;
      const dy = p.y - this.punteroPrev.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) this.movio = true;
      // Desplazar el objetivo en el plano de la cámara
      const escala = 0.02 / this.cam.zoom;
      const derecha = new THREE.Vector3().subVectors(this.camara.position, this.cam.objetivo).normalize();
      const up = new THREE.Vector3(0, 1, 0);
      const fwd = new THREE.Vector3().crossVectors(derecha, up).normalize();
      const right = new THREE.Vector3().crossVectors(up, fwd).normalize();
      // Proyectar movimiento de pantalla a los ejes de la cámara (plano XZ)
      const moveX = dx * escala;
      const moveZ = dy * escala * 1.15;
      this.cam.objetivo.addScaledVector(right, moveX);
      this.cam.objetivo.addScaledVector(fwd, moveZ);
      this.cam.objetivo.y = 0;
      this.punteroPrev = p;
      this.aplicarCamara(this.ancho, this.alto);
      return;
    }

    // Hover
    const hit = this.interseccion(p.x, p.y);
    const cambioHover =
      hit.agente?.id !== this.hoverAgente?.id || hit.depto !== this.hoverDepto || hit.wall !== this.hoverWall;
    this.hoverAgente = hit.agente;
    this.hoverDepto = hit.depto;
    this.hoverWall = hit.wall;
    if (cambioHover) this.refrescarResaltado();
    this.canvas.style.cursor = hit.agente || hit.depto || hit.wall ? "pointer" : "grab";
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
    const eraGesto = this.punteros.size > 1;
    this.punteros.delete(e.pointerId);
    if (this.punteros.size < 2) this.pinchPrev = null;
    if (!this.arrastrando) return;
    this.arrastrando = false;
    if (this.movio || eraGesto) return;

    const p = this.pos(e);
    const hit = this.interseccion(p.x, p.y);
    if (hit.agente) {
      this.seleccionarAgente(hit.agente);
      this.cb.onAgente(hit.agente);
      this.cb.onDepto(null);
      this.cb.onWall(false);
      return;
    }
    if (hit.wall) {
      this.cb.onAgente(null);
      this.cb.onDepto(null);
      this.cb.onWall(true);
      return;
    }
    if (hit.depto) {
      this.seleccionarDepto(hit.depto);
      this.cb.onAgente(null);
      this.cb.onWall(false);
      this.cb.onDepto(hit.depto);
      this.enfocarDepto(hit.depto);
    } else {
      this.seleccionarDepto(null);
      this.cb.onAgente(null);
      this.cb.onWall(false);
      this.cb.onDepto(null);
    }
  };

  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    this.cam.zoom = limitarZoom(this.cam.zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
    this.foco = null;
    this.aplicarCamara(this.ancho, this.alto);
  };

  private interseccion(sx: number, sy: number): { agente: AgenteOficina | null; depto: string | null; wall: boolean } {
    const r = this.canvas.getBoundingClientRect();
    this.punteroNdc.set(((sx - r.left) / r.width) * 2 - 1, -((sy - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.punteroNdc, this.camara);
    const objs = [...this.meshesAgente.values(), ...this.meshesDepto.values(), ...this.meshesWall];
    const hits = this.raycaster.intersectObjects(objs, true);

    let wall = false;
    let depto: string | null = null;
    let agente: AgenteOficina | null = null;

    for (const h of hits) {
      let o: THREE.Object3D | null = h.object;
      while (o) {
        if (o.userData.esWall) {
          wall = true;
          break;
        }
        if (o.userData.agenteId && !agente) {
          const id = o.userData.agenteId as string;
          agente = this.datos.departamentos.flatMap((d) => d.agentes).find((a) => a.id === id) ?? null;
        }
        if (o.userData.deptoId && !depto) depto = o.userData.deptoId as string;
        o = o.parent;
      }
      if (wall || (agente && depto)) break;
    }

    return { agente, depto, wall };
  }

  private refrescarResaltado() {
    for (const [id, grupo] of this.meshesDepto) {
      const sel = this.deptoSel === id;
      const hov = this.hoverDepto === id;
      grupo.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        const mat = mesh.material as THREE.MeshStandardMaterial | THREE.MeshPhysicalMaterial | undefined;
        if (!mat || !("emissiveIntensity" in mat)) return;
        const esSuelo = mesh.geometry?.type === "BoxGeometry" && mesh.position.y < 0.2;
        if (sel) mat.emissiveIntensity = esSuelo ? 0.28 : 0.2;
        else if (hov) mat.emissiveIntensity = esSuelo ? 0.18 : 0.12;
        else if (esSuelo) mat.emissiveIntensity = 0.06;
      });
      const et = this.etiquetasDepto.get(id);
      if (et) {
        const s = sel ? 1.22 : hov ? 1.08 : 1;
        et.scale.set(4.8 * s, 0.9 * s, 1);
      }
    }
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
      const zoomDestino = this.foco.zoom ?? this.cam.zoom;
      const k = 1 - Math.pow(0.0015, dt);
      this.cam.objetivo.lerp(this.foco.objetivo, k);
      this.cam.zoom += (zoomDestino - this.cam.zoom) * k;
      if (this.cam.objetivo.distanceTo(this.foco.objetivo) < 0.05 && Math.abs(zoomDestino - this.cam.zoom) < 0.005) {
        this.cam.objetivo.copy(this.foco.objetivo);
        this.cam.zoom = zoomDestino;
        this.foco = null;
      }
      this.aplicarCamara(this.ancho, this.alto);
    }

    // Animación de agentes
    for (const a of this.agentesAnim) {
      const trabajando = a.estado === "trabajando";
      const alerta = a.estado === "alerta";
      const bob = trabajando
        ? Math.sin(this.t * 3.2 + a.fase) * 0.04
        : Math.sin(this.t * 1.1 + a.fase) * 0.015;
      a.grupo.position.y = a.yBase + bob;
      if (alerta) {
        a.grupo.traverse((obj) => {
          const mesh = obj as THREE.Mesh;
          if (!mesh.userData.esAnillo) return;
          const s = 1 + Math.sin(this.t * 5) * 0.15;
          mesh.scale.setScalar(s);
        });
      }
    }

    // Parpadeo tenue de luces de monitor
    this.lucesMonitores.forEach((l, i) => {
      l.intensity = 0.28 + Math.sin(this.t * 2 + i) * 0.06;
    });

    this.renderer.render(this.scene, this.camara);
  };
}

function limitarZoom(z: number): number {
  return Math.min(2.4, Math.max(0.45, z));
}

/** PRNG determinista para el skyline de demo. */
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
