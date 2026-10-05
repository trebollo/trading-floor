"""Execution & Ops: broker de papel, router con guardarraíles, ledger y reconciliación
(spec 05).

El router es determinista (sin LLM en el camino de la orden, E-9), verifica el
risk_token firmado (E-2), aplica idempotencia (E-5), límites de frecuencia (E-6) y
puede auto-suspenderse (E-7).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from tf.risk import verify_risk_token, RiskTokenError


# ---------------------------------------------------------------------------
# Broker de papel
# ---------------------------------------------------------------------------


@dataclass
class PaperFill:
    order_id: str
    instrument: str
    side: str
    size: float
    price: float
    ts: float


class PaperBroker:
    """Simulador de broker: llena al precio siguiente disponible + slippage."""

    def __init__(self, slippage_rate: float = 0.0003) -> None:
        self.slippage_rate = slippage_rate
        self.positions: dict[str, dict[str, Any]] = {}  # instrument → {side, size}
        self.fills: list[PaperFill] = []
        self.reject_next_orders = False  # inyección de fallos para tests/caos

    def place(self, order_id: str, instrument: str, side: str, size: float, price: float, ts: float | None = None) -> PaperFill:
        if self.reject_next_orders:
            raise BrokerRejected("broker rechaza la orden (inyección de fallo)")
        fill_price = price * (1 + self.slippage_rate * (1 if side == "BUY" else -1))
        fill = PaperFill(order_id=order_id, instrument=instrument, side=side, size=size, price=fill_price, ts=ts if ts is not None else time.time())
        self.fills.append(fill)
        self._apply(fill)
        return fill

    def _apply(self, fill: PaperFill) -> None:
        pos = self.positions.get(fill.instrument)
        if pos is None or pos["side"] == fill.side:
            if pos is None:
                self.positions[fill.instrument] = {"side": fill.side, "size": fill.size}
            else:
                pos["size"] += fill.size
        else:  # cierra o reduce
            remaining = pos["size"] - fill.size
            if remaining <= 1e-12:
                if remaining < -1e-12:
                    self.positions[fill.instrument] = {"side": fill.side, "size": -remaining}
                else:
                    del self.positions[fill.instrument]
            else:
                pos["size"] = remaining


class BrokerRejected(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Ledger (bookkeeper, apéndice-only)
# ---------------------------------------------------------------------------


class Ledger:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def append_fill(self, fill: PaperFill, strategy_id: str) -> dict[str, Any]:
        entry = {
            "kind": "FILL",
            "order_id": fill.order_id,
            "instrument": fill.instrument,
            "side": fill.side,
            "size": fill.size,
            "price": fill.price,
            "strategy_id": strategy_id,
            "ts": fill.ts,
        }
        self.entries.append(entry)
        return entry

    def positions(self) -> dict[str, dict[str, Any]]:
        """Reconstruye posiciones del ledger (replay de eventos)."""
        positions: dict[str, dict[str, Any]] = {}
        for e in self.entries:
            pos = positions.get(e["instrument"])
            if pos is None or pos["side"] == e["side"]:
                if pos is None:
                    positions[e["instrument"]] = {"side": e["side"], "size": e["size"]}
                else:
                    pos["size"] += e["size"]
            else:
                remaining = pos["size"] - e["size"]
                if remaining <= 1e-12:
                    if remaining < -1e-12:
                        positions[e["instrument"]] = {"side": e["side"], "size": -remaining}
                    else:
                        del positions[e["instrument"]]
                else:
                    pos["size"] = remaining
        return positions


def reconcile(broker_positions: dict[str, dict[str, Any]], ledger_positions: dict[str, dict[str, Any]]) -> list[str]:
    """Discrepancias entre broker y ledger. El broker manda hasta resolver (E-8)."""
    issues = []
    for instrument in sorted(set(broker_positions) | set(ledger_positions)):
        b = broker_positions.get(instrument)
        l = ledger_positions.get(instrument)
        if b is None or l is None or b["side"] != l["side"] or abs(b["size"] - l["size"]) > 1e-9:
            issues.append(f"{instrument}: broker={b} ledger={l}")
    return issues


# ---------------------------------------------------------------------------
# Execution Router
# ---------------------------------------------------------------------------


class RouterSuspended(RuntimeError):
    pass


class ExecutionRouter:
    """Único punto de contacto con el broker. Determinista (E-1/E-9)."""

    def __init__(
        self,
        broker: PaperBroker,
        secret: str,
        max_orders_per_minute: int = 30,
        max_consecutive_rejects: int = 5,
        ledger: Ledger | None = None,
    ) -> None:
        if not secret:
            raise ValueError("el router exige secreto para verificar risk_tokens (E-2)")
        self.broker = broker
        self.secret = secret
        self.ledger = ledger or Ledger()
        self.max_orders_per_minute = max_orders_per_minute
        self.max_consecutive_rejects = max_consecutive_rejects
        self._sent_timestamps: deque[float] = deque()
        self._seen_request_ids: set[str] = set()
        self._consecutive_rejects = 0
        self.suspended = False

    # -- guardarraíles ------------------------------------------------------------

    def _check_frequency(self, now: float) -> None:
        while self._sent_timestamps and now - self._sent_timestamps[0] > 60.0:
            self._sent_timestamps.popleft()
        if len(self._sent_timestamps) >= self.max_orders_per_minute:
            raise RuntimeError("E-6: límite de frecuencia de órdenes alcanzado")

    def _check_alive(self) -> None:
        if self.suspended:
            raise RouterSuspended("E-7: router auto-suspendido")

    # -- envío ---------------------------------------------------------------------

    def execute(
        self,
        request: dict[str, Any],
        risk_token: str,
        price: float,
        now: float | None = None,
        ts: float | None = None,
    ) -> PaperFill:
        self._check_alive()
        now = now if now is not None else time.time()

        # E-5: idempotencia por request_id.
        request_id = request["request_id"]
        if request_id in self._seen_request_ids:
            raise RuntimeError("E-5: request_id duplicado; el reintento no debe duplicar posición")
        self._seen_request_ids.add(request_id)

        # E-2: verificación del token firmado (identidad, tamaño, expiración).
        try:
            payload = verify_risk_token(risk_token, self.secret, now=now)
        except RiskTokenError:
            self._register_reject()
            raise
        if payload["request_id"] != request_id:
            self._register_reject()
            raise RiskTokenError("E-2: token no corresponde a esta orden")
        size = min(float(request["size"]), float(payload["max_size"]))  # REDUCIR ⇒ clamp al token
        if size > payload["max_size"] + 1e-12:
            self._register_reject()
            raise RiskTokenError(f"E-2: tamaño {size} excede el autorizado {payload['max_size']}")

        # E-6: frecuencia.
        self._check_frequency(now)
        self._sent_timestamps.append(now)

        # Envío al broker con gestión de rechazos (E-7).
        order_id = f"ord-{request_id}"
        try:
            fill = self.broker.place(order_id, request["instrument"], request["side"], size, price, ts=ts)
        except BrokerRejected:
            self._register_reject()
            raise
        self._consecutive_rejects = 0
        self.ledger.append_fill(fill, payload["strategy_id"])
        return fill

    def _register_reject(self) -> None:
        self._consecutive_rejects += 1
        if self._consecutive_rejects >= self.max_consecutive_rejects:
            self.suspended = True  # E-7: auto-suspensión ante anomalías
