"""Event bus: transporte de sobrés validados en el borde (G2).

Fase 0 usa `InMemoryBus` (despacho síncrono, determinista para tests). La interfaz
es la misma que implementará el adaptador de NATS JetStream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from tf.contracts import Envelope, validate_payload

Handler = Callable[[Envelope], None]


class BaseBus(ABC):
    @abstractmethod
    def publish(self, envelope: Envelope) -> None: ...

    @abstractmethod
    def subscribe(self, msg_type: str, handler: Handler) -> None: ...

    def publish_raw(self, msg_type: str, payload: dict[str, Any], **envelope_kwargs: Any) -> Envelope:
        env = Envelope(type=msg_type, payload=payload, **envelope_kwargs)
        self.publish(env)
        return env


class InMemoryBus(BaseBus):
    """Despacho síncrono en orden de suscripción. Valida el payload al publicar."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.published: list[Envelope] = []

    def subscribe(self, msg_type: str, handler: Handler) -> None:
        self._handlers[msg_type].append(handler)

    def publish(self, envelope: Envelope) -> None:
        # G2: la misma validación en el borde que el bus en memoria.
        validate_payload(envelope.type, envelope.payload)
        self.published.append(envelope)
        for handler in self._handlers.get(envelope.type, []):
            handler(envelope)
