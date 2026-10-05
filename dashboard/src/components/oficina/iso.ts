// Matemática isométrica 2:1 y cámara.

export const TILE_W = 64;
export const TILE_H = 32;

export interface Camara {
  /** Desplazamiento en píxeles de pantalla del origen del mundo. */
  x: number;
  y: number;
  zoom: number;
}

export const ZOOM_MIN = 0.45;
export const ZOOM_MAX = 2.4;

export function mundoAPantalla(wx: number, wy: number, cam: Camara): { sx: number; sy: number } {
  return {
    sx: (wx - wy) * (TILE_W / 2) * cam.zoom + cam.x,
    sy: (wx + wy) * (TILE_H / 2) * cam.zoom + cam.y,
  };
}

export function pantallaAMundo(sx: number, sy: number, cam: Camara): { wx: number; wy: number } {
  const px = (sx - cam.x) / cam.zoom;
  const py = (sy - cam.y) / cam.zoom;
  return {
    wx: px / TILE_W + py / TILE_H,
    wy: py / TILE_H - px / TILE_W,
  };
}

/** Centro de la cámara de forma que el punto del mundo quede en el centro de la pantalla. */
export function camaraCentradaEn(wx: number, wy: number, ancho: number, alto: number, zoom: number): Camara {
  return {
    zoom,
    x: ancho / 2 - (wx - wy) * (TILE_W / 2) * zoom,
    y: alto / 2 - (wx + wy) * (TILE_H / 2) * zoom,
  };
}

export function limitarZoom(z: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
}

/** Zoom alrededor de un punto de pantalla (mantener el punto bajo el cursor). */
export function zoomEnPunto(cam: Camara, factor: number, px: number, py: number): Camara {
  const zoom = limitarZoom(cam.zoom * factor);
  const mundo = pantallaAMundo(px, py, cam);
  return {
    zoom,
    x: px - (mundo.wx - mundo.wy) * (TILE_W / 2) * zoom,
    y: py - (mundo.wx + mundo.wy) * (TILE_H / 2) * zoom,
  };
}
