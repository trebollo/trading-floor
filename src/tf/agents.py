"""Esqueleto de agente: sin estado, con heartbeat, broker y audit log.

Fase 0: el bucle y el ciclo de publicación ya quedan fijados con sus guardarraíles;
los departamentos concretos enchufan su lógica en `handle()` a partir de Fase 1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from tf.audit import AuditLog
from tf.bus import BaseBus
from tf.contracts import Actor, Envelope, MessageValidationError
from tf.permissions import PermissionBroker


class Agent(ABC):
    department: str = "unset"
    subscriptions: tuple[str, ...] = ()

    def __init__(
        self,
        name: str,
        role: str,
        bus: BaseBus,
        broker: PermissionBroker,
        audit: AuditLog,
        gateway: Any | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.bus = bus
        self.broker = broker
        self.audit = audit
        self.gateway = gateway
        # Validación de permisos en arranque: un agente sin política no arranca (G1).
        broker.policy(name)

    # -- identidad --------------------------------------------------------------

    @property
    def actor(self) -> Actor:
        model = None
        if self.gateway is not None:
            try:
                model = self.gateway.resolve(self.name, "generative").name
            except KeyError:
                model = None
        return Actor(agent=self.name, role=self.role, department=self.department, model=model)

    # -- publicación con guardarrail -------------------------------------------

    def publish(self, msg_type: str, payload: dict[str, Any], **envelope_kwargs: Any) -> Envelope:
        # G1: solo puede publicar lo que su política declara.
        # El heartbeat se permite incluso suspendido: es la señal de salud (G6).
        ignore_suspension = msg_type == "agent.heartbeat.v1"
        self.broker.check_publish(self.name, msg_type, ignore_suspension=ignore_suspension)
        env = Envelope(
            type=msg_type, payload=payload, actor=self.actor.model_dump(), **envelope_kwargs
        )
        try:
            self.bus.publish(env)
        except MessageValidationError:
            # G2: salida inválida nunca se publica; se registra y cuenta para calidad.
            self.audit.append(
                actor=self.name,
                event_type="agent.output_invalid",
                payload={"message_type": msg_type, "payload": payload},
            )
            raise
        return env

    # -- herramientas con guardarrail -------------------------------------------

    def use_tool(self, tool: str, fn, /, *args: Any, **kwargs: Any) -> Any:
        """Punto único de acceso a herramientas: pasa por el Permission Broker (G1)."""
        self.broker.check_tool(self.name, tool)
        self.audit.append(
            actor=self.name,
            event_type="tool.call",
            payload={"tool": tool, "args": len(args) + len(kwargs)},
        )
        return fn(*args, **kwargs)

    # -- ciclo de vida ----------------------------------------------------------

    def heartbeat(self) -> Envelope:
        return self.publish(
            "agent.heartbeat.v1",
            {
                "agent": self.name,
                "department": self.department,
                "status": "degraded" if self.broker.is_suspended(self.name) else "up",
                "subscriptions": list(self.subscriptions),
            },
        )

    @abstractmethod
    def handle(self, envelope: Envelope) -> None:
        """Procesa un mensaje de suscripción. Sin estado: todo se publica, nada se guarda."""

    def receive(self, envelope: Envelope) -> None:
        """Punto de entrada del bus. Errores de negocio no tumban al agente (P5)."""
        try:
            self.handle(envelope)
        except Exception as exc:
            self.audit.append(
                actor=self.name,
                event_type="agent.handler_error",
                payload={"envelope_id": envelope.id, "type": envelope.type, "error": str(exc)},
            )
            raise
