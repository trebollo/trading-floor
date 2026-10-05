# Especificación: Macro & News Department

*Guardarraíles transversales: ver [00-marco-guardarrailes.md](00-marco-guardarrailes.md).*

## 1. Misión y alcance

Mantener un mapa actualizado del régimen de mercado y de los eventos (noticias,
calendario económico) que pueden cambiar el riesgo del portfolio, y publicarlo como
información estructurada que consumen Research, Validation y Risk. **No opera, no
prohíbe, no ordena**: publica información con la máxima seriedad posible sobre su
incertidumbre.

## 2. Agentes

### 2.1 `macro-analyst` (×1)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Clasificar el régimen de mercado (tendencia/rango, riesgo on/off, ciclo de tipos, volatilidad) a partir de indicadores macro y de mercado |
| Modelo | Generativo `frontier-lite` (redacta el análisis) + `decisions: jev` (clasificación tipada de régimen y confianza) |
| Herramientas (G1) | `read_market_data` (series macro y de mercado), `read_calendar`, `publish_regime` |
| Publica | `macro.regime.v1` (cada 4 h o al cambiar), `macro.outlook.v1` (diario) |

### 2.2 `news-analyst` (×2, redundantes por fuente)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Ingesta y análisis continuo de noticias y calendario; triaje de relevancia; alertas de eventos de cola |
| Modelo | Generativo `frontier-lite` (resumen) + `decisions: jev` (triaje: relevante / acción / ruido; probabilidad de impacto) |
| Herramientas (G1) | `fetch_news` (fuentes de la whitelist), `read_calendar`, `search_memory`, `publish_alert` |
| Publica | `news.alert.v1`, `news.digest.v1` |

## 3. Guardarraíles específicos

| # | Guardarrail | Tipo |
|---|---|---|
| M-1 | **Solo publica información:** prohibido para ambos roles publicar `order.request`, `directive`, límites o veredictos; sus mensajes no pueden accionar órdenes, solo restricciones que Risk decide aplicar | G5 |
| M-2 | **Whitelist de fuentes:** solo fuentes preaprobadas por el CEO; toda afirmación cuantitativa (datos, cifras, fechas) debe citar un campo estructurado de la fuente; cita ausente ⇒ la afirmación se elimina del mensaje (anti-alucinación) | G5 |
| M-3 | **Etiquetado obligatorio de incertidumbre:** todo régimen y alerta lleva `confidence` y `horizon`; Risk no aplica restricciones automáticas por debajo de la confianza mínima configurada | G5 |
| M-4 | **Eventos de cola no retencibles:** si el triaje marca un evento como `TAIL_RISK` (probabilidad de impacto > umbral), la alerta se publica inmediatamente; retenerla o esperar "más contexto" es violación V3 | G5 |
| M-5 | **Latencia máxima de triaje:** 60 s por noticia para la decisión de triaje (Jev); el resumen redactado puede llegar después | G3/G5 |
| M-6 | **Duplicación por fuente:** los dos news-analysts cubren fuentes distintas; una alerta de cola confirmada por una sola fuente se publica con `single_source: true` y Risk aplica margen extra | G5 |
| M-7 | **Sin acceso a posiciones ni órdenes:** el departamento no conoce la cartera (evita sesgos de confirmación y filtraciones) | G4 |
| M-8 | **Modo defensa solo propuesto:** ante evento de cola, puede *solicitar* a Risk la activación de un modo de defensa predefinido; Risk decide | G5/G7 |

## 4. Modos de fallo y degradación

- **Feed de noticias caído:** incidente a Risk + Ops; se activa el perfil conservador de
  calendario (restricciones por eventos programados aunque no haya noticias en vivo).
- **Jev caído:** el triaje pasa a reglas por palabras clave y calendario; la confianza de
  todas las alertas se marca baja; Risk aplica margen extra automático.
- **Macro sin datos actualizados:** publica `macro.regime.v1` con `stale: true`; Validation
  no puede completar su batería (ver spec 03) y Risk tensa límites.

## 5. KPIs del departamento

Latencia noticia→alerta · precisión del triaje (evaluada contra el impacto real semanal) ·
estabilidad del etiquetado de régimen (cambios de régimen/semana no justificados) ·
cobertura de fuentes · % de eventos de cola capturados antes del impacto.
