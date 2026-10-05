"""Host multiagente: cada departamento es independiente, todos comparten el bus.

El `AgentHost` convierte el bus de sobrés en una orquestación real: registra
departamentos con uno o más workers (subagentes especializados), despacha los
mensajes a sus suscripciones y aplica las guardas anti-bucle obligatorias:

  · Dedup por `envelope.id`     — un mensaje re-encolado (bucle) se audita como
                                  `agent.loop_blocked` y se descarta.
  · Cola acotada por host       — si un departamento no consume, el desbordamiento
                                  se audita (`host.queue_overflow`) y se descarta:
                                  la presión nunca crece sin límite.
  · `drain(max_steps)`          — cada ciclo de drenaje tiene un techo de pasos;
                                  un sistema que se contesta a sí mismo no puede
                                  correr indefinidamente.

Los workers no son agentes completos: son handlers `(Envelope) -> list[Envelope]`
que devuelven los mensajes de salida que el host publica en el bus. Un worker que
lanza excepción no tumba el host: el error se audita como `agent.error`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tf.audit import AuditLog
from tf.bus import BaseBus
from tf.contracts import Envelope

# Handler de worker: recibe el sobre, devuelve sobres de salida (o lista vacía).
Worker = Callable[[Envelope], list[Envelope] | None]


@dataclass
class _Mailbox:
    queue: list[Envelope] = field(default_factory=list)

    def push(self, env: Envelope) -> bool:
        """True si cabía (el host impone el techo); False si está saturada."""
        self.queue.append(env)
        return True

    def pop(self) -> Envelope | None:
        return self.queue.pop(0) if self.queue else None


class AgentHost:
    """Contenedor de departamentos con despacho acotado y anti-bucle (G3/G7)."""

    def __init__(
        self,
        bus: BaseBus,
        audit: AuditLog,
        max_queue: int = 1000,
        max_steps: int = 500,
        actor: str = "host",
    ) -> None:
        self.bus = bus
        self.audit = audit
        self.max_queue = max_queue
        self.max_steps = max_steps
        self.actor = actor
        self.departments: dict[str, list[str]] = {}
        self._subscriptions: dict[str, list[Worker]] = defaultdict(list)
        self._mailboxes: dict[str, _Mailbox] = {}
        self._seen: set[str] = set()
        self._dropped_for_dedup = 0
        self._dropped_for_overflow = 0

    # -- registro ------------------------------------------------------------

    def register(self, department: str, workers: dict[str, Worker], msg_types: dict[str, list[str]]) -> None:
        """Registra un departamento.

        `workers`: nombre → handler. `msg_types`: nombre de worker → tipos de
        mensaje a los que se suscribe. Las suscripciones se hacen sobre el bus;
        el host retiene los workers para el drenaje acotado.
        """
        self.departments.setdefault(department, []).extend(workers)
        for worker_name, worker in workers.items():
            for msg_type in msg_types.get(worker_name, []):
                self._subscriptions[msg_type].append(worker)
                self.bus.subscribe(msg_type, self._make_subscriber(worker_name))

    def _make_subscriber(self, worker_name: str) -> Callable[[Envelope], None]:
        """Handler de bus: encola para el drenaje acotado en vez de ejecutar en línea."""

        def _enqueue(env: Envelope) -> None:
            mailbox = self._mailboxes.setdefault(worker_name, _Mailbox())
            if len(mailbox.queue) >= self.max_queue:
                self._dropped_for_overflow += 1
                self._audit("host.queue_overflow", {"worker": worker_name, "envelope_id": env.id})
                return
            mailbox.push(env)

        return _enqueue

    # -- drenaje ----------------------------------------------------------------

    def drain(self, max_steps: int | None = None) -> dict[str, Any]:
        """Procesa la cola hasta vaciarla o agotar `max_steps` (techo anti-bucle)."""
        limit = self.max_steps if max_steps is None else max_steps
        steps = 0
        while steps < limit:
            env = self._next_envelope()
            if env is None:
                break
            steps += 1
            if env.id in self._seen:
                self._dropped_for_dedup += 1
                self._audit("agent.loop_blocked", {"envelope_id": env.id, "type": env.type})
                continue
            self._seen.add(env.id)
            for worker in self._subscriptions.get(env.type, []):
                try:
                    outputs = worker(env)
                except Exception as exc:  # un worker caído no tumba al host
                    self._audit(
                        "agent.error",
                        {"worker": getattr(worker, "__name__", "?"), "type": env.type,
                         "error": f"{type(exc).__name__}: {exc}"},
                    )
                    continue
                for out in outputs or []:
                    self.bus.publish(out)  # puede re-encolar en otros workers (o en este)
        return {"steps": steps, "pending": self._pending(), "dropped_dedup": self._dropped_for_dedup, "dropped_overflow": self._dropped_for_overflow}

    # -- estado interno -----------------------------------------------------------

    def _next_envelope(self) -> Envelope | None:
        for mailbox in self._mailboxes.values():
            env = mailbox.pop()
            if env is not None:
                return env
        return None

    def _pending(self) -> int:
        return sum(len(m.queue) for m in self._mailboxes.values())

    def _audit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.audit.append(actor=self.actor, event_type=event_type, payload=payload)


def Department(name: str, workers: dict[str, Worker], msg_types: dict[str, list[str]]) -> dict[str, Any]:
    """Descripción declarativa de un departamento, para `host.register(**dept)`."""
    return {"department": name, "workers": workers, "msg_types": msg_types}
