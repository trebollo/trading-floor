"""Risk Department: gate pre-trade determinista + tokens firmados (spec 04).

Reglas fijadas en código (K-1/K-4): el gate es aritmética contra límites, no opinión.
Fail-closed universal (K-2): ante cualquier dato ausente, rechazo técnico.
Los agentes LLM nunca autorizan; solo este núcleo decide.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuración: límites (solo el CEO los cambia, K-5) y contratos por estrategia
# ---------------------------------------------------------------------------


class RiskLimits(BaseModel):
    """Límites duros del sistema. Configuración versionada con doble confirmación."""

    max_risk_per_trade: float = 0.005          # fracción del capital
    max_exposure_per_instrument: float = 0.20  # fracción del capital
    max_leverage: float = 1.0                  # exposición total / capital
    max_daily_drawdown: float = 0.03           # superado ⇒ solo-cierre
    max_total_drawdown: float = 0.15           # superado ⇒ solo-cierre
    max_open_positions_same_group: int = 3
    universe: list[str] = Field(default_factory=lambda: ["SYNTH"])
    token_ttl_seconds: int = 60


class StrategyContract(BaseModel):
    """Contrato de riesgo firmado al aprobar una estrategia (§6 arquitectura)."""

    strategy_id: str
    max_size: float = Field(gt=0, description="tamaño máximo por orden (fracción del capital)")
    universe: list[str] = Field(default_factory=list)
    require_stop: bool = True
    max_own_drawdown: float = 0.10
    only_normal_regime: bool = False  # restricción de estrategias VALIDADA_PROVISIONAL


# ---------------------------------------------------------------------------
# Estado del portfolio que consume el gate (snapshot determinista)
# ---------------------------------------------------------------------------


@dataclass
class PositionInfo:
    instrument: str
    side: str            # "BUY" (largo) o "SELL" (corto)
    size: float          # fracción del capital
    group: str = "default"


@dataclass
class PortfolioState:
    equity: float
    equity_start_of_day: float
    equity_peak: float
    positions: dict[str, PositionInfo] = field(default_factory=dict)  # por instrumento

    @property
    def daily_drawdown(self) -> float:
        if self.equity_start_of_day <= 0:
            return 0.0
        return max(0.0, 1.0 - self.equity / self.equity_start_of_day)

    @property
    def total_drawdown(self) -> float:
        if self.equity_peak <= 0:
            return 0.0
        return max(0.0, 1.0 - self.equity / self.equity_peak)

    def total_exposure(self) -> float:
        return sum(p.size for p in self.positions.values())


class MissingStateError(RuntimeError):
    """Estado incompleto: el gate debe fallar cerrando (K-2)."""


# ---------------------------------------------------------------------------
# Tokens de riesgo firmados (K-3)
# ---------------------------------------------------------------------------


class RiskTokenError(ValueError):
    pass


def issue_risk_token(
    request_id: str,
    strategy_id: str,
    instrument: str,
    side: str,
    max_size: float,
    secret: str,
    ttl_seconds: int,
    now: float | None = None,
) -> str:
    payload = {
        "request_id": request_id,
        "strategy_id": strategy_id,
        "instrument": instrument,
        "side": side,
        "max_size": max_size,
        "exp": (now if now is not None else time.time()) + ttl_seconds,
    }
    body = urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_risk_token(token: str, secret: str, now: float | None = None) -> dict[str, Any]:
    """Verifica firma y TTL. Lanza RiskTokenError si el token es inválido o expiró."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        raise RiskTokenError("token mal formado") from None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise RiskTokenError("firma inválida")
    payload = json.loads(__import__("base64").urlsafe_b64decode(body.encode()))
    if now is None:
        now = time.time()
    if now > payload["exp"]:
        raise RiskTokenError("token expirado")
    return payload


# ---------------------------------------------------------------------------
# Gate pre-trade
# ---------------------------------------------------------------------------

AUTORIZADA, REDUCIR, RECHAZADA = "AUTORIZADA", "REDUCIR", "RECHAZADA"


@dataclass
class GateDecision:
    verdict: str
    max_size: float | None
    reason: str
    technical: bool = False
    risk_token: str | None = None

    @property
    def authorized(self) -> bool:
        return self.verdict in (AUTORIZADA, REDUCIR) and self.risk_token is not None


class PreTradeGate:
    """Núcleo determinista de autorización. Sin LLM, sin excepciones (K-1..K-4)."""

    def __init__(self, limits: RiskLimits, secret: str) -> None:
        if not secret:
            raise ValueError("el gate exige un secreto de firma; sin él no arranca (K-1)")
        self.limits = limits
        self._secret = secret

    def allowed_universe(self, contract: StrategyContract) -> set[str]:
        return set(contract.universe) & set(self.limits.universe)

    def check(
        self,
        request: dict[str, Any],
        contract: StrategyContract | None,
        state: PortfolioState | None,
        regime: str | None = None,
        now: float | None = None,
    ) -> GateDecision:
        # K-2: fail-closed ante estado o contrato ausente.
        if contract is None:
            return self._reject(request, "sin contrato de riesgo firmado", technical=True)
        if state is None or state.equity <= 0:
            return self._reject(request, "estado de portfolio no disponible", technical=True)

        instrument = request.get("instrument")
        side = request.get("side")
        size = request.get("size")
        if instrument is None or side not in ("BUY", "SELL") or size is None or size <= 0:
            return self._reject(request, "orden mal formada", technical=True)

        closes_position = self._closes_position(request, state)
        pos = state.positions.get(instrument)

        # Modo solo-cierre por drawdown (límites diarios y totales).
        if state.daily_drawdown >= self.limits.max_daily_drawdown:
            if not closes_position:
                return self._reject(request, f"drawdown diario {state.daily_drawdown:.2%} ≥ límite: modo solo-cierre")
        if state.total_drawdown >= self.limits.max_total_drawdown:
            if not closes_position:
                return self._reject(request, f"drawdown total {state.total_drawdown:.2%} ≥ límite: modo solo-cierre")

        # Vetos absolutos (§3 spec 04).
        if instrument not in self.allowed_universe(contract):
            return self._reject(request, f"{instrument} fuera del universo autorizado")
        if contract.require_stop and request.get("stop_loss") is None and not closes_position:
            return self._reject(request, "el contrato exige stop; orden sin stop rechazada (E-4)")
        if contract.only_normal_regime and regime == "adverso" and not closes_position:
            return self._reject(request, "contrato provisional: sin aperturas en régimen adverso")

        # Cerrar posiciones siempre reduce riesgo: sin caps de tamaño (solo-cierre).
        if closes_position:
            token = issue_risk_token(
                request_id=request["request_id"], strategy_id=contract.strategy_id,
                instrument=instrument, side=side, max_size=size,
                secret=self._secret, ttl_seconds=self.limits.token_ttl_seconds, now=now,
            )
            return GateDecision(verdict=AUTORIZADA, max_size=size, reason="cierre de posición", risk_token=token)

        # Riesgo por operación: reducción antes que rechazo.
        max_size = min(size, contract.max_size, self.limits.max_risk_per_trade)
        # Exposición por instrumento tras la orden.
        current = pos.size if pos and pos.side == side else 0.0
        headroom = self.limits.max_exposure_per_instrument - current
        max_size = min(max_size, max(headroom, 0.0))
        if max_size <= 0:
            return self._reject(request, f"exposición máxima de {instrument} alcanzada")

        # Apalancamiento global tras la orden.
        projected = state.total_exposure() - (pos.size if pos else 0.0) + current + max_size
        if projected > self.limits.max_leverage + 1e-9:
            max_size = min(max_size, max(self.limits.max_leverage - state.total_exposure() + (pos.size if pos else 0.0) - current, 0.0))
            if max_size <= 0:
                return self._reject(request, "apalancamiento máximo alcanzado")

        # Posiciones correlacionadas (mismo grupo) — solo aperturas nuevas.
        if not pos:
            group_count = sum(1 for p in state.positions.values() if p.group == "default")
            if group_count >= self.limits.max_open_positions_same_group:
                return self._reject(request, "máximo de posiciones correlacionadas alcanzado")

        verdict = AUTORIZADA if max_size >= size else REDUCIR
        token = issue_risk_token(
            request_id=request["request_id"],
            strategy_id=contract.strategy_id,
            instrument=instrument,
            side=side,
            max_size=max_size,
            secret=self._secret,
            ttl_seconds=self.limits.token_ttl_seconds,
            now=now,
        )
        reason = "cumple todos los límites" if verdict == AUTORIZADA else f"tamaño reducido a {max_size:.4f} por límites"
        return GateDecision(verdict=verdict, max_size=max_size, reason=reason, risk_token=token)

    # -- helpers -----------------------------------------------------------------

    @staticmethod
    def _closes_position(request: dict[str, Any], state: PortfolioState) -> bool:
        pos = state.positions.get(request.get("instrument"))
        return pos is not None and pos.side != request.get("side")

    def _reject(self, request: dict[str, Any], reason: str, technical: bool = False) -> GateDecision:
        return GateDecision(verdict=RECHAZADA, max_size=None, reason=reason, technical=technical)
