"""Tests del Model Gateway con proveedores reales (offline: HTTP simulado)."""

import io
import json

import pytest

from tf.gateway import GatewayConfig, JevClient, ModelGateway, OpenAICompatClient, OpenAIResponsesClient
from tf.pipeline import ResearchTemplateAgent

# ---------------------------------------------------------------------------
# Fixtures: gateway y agentes sin permisos reales
# ---------------------------------------------------------------------------


def make_gateway() -> ModelGateway:
    config = GatewayConfig.model_validate(
        {
            "models": {
                "jev": {
                    "kind": "evaluator",
                    "id": "typesafe-ai/jev",
                    "provider": "vercel-ai-gateway",
                    "endpoint": "https://ai-gateway.vercel.sh/typesafe/v1",
                    "api_key_env": "AI_GATEWAY_API_KEY",
                },
                "writer": {
                    "kind": "generative",
                    "id": "gpt-6-luna",
                    "provider": "opencode-go",
                    "endpoint": "https://opencode.ai/zen/go/v1",
                    "api_key_env": "OPENCODE_API_KEY",
                },
                "no-provider": {"kind": "generative"},
            },
            "agents": {
                "research-hypothesis": {"generative": "writer", "decisions": "jev"},
                "plain-agent": {"generative": "no-provider"},
            },
        }
    )
    return ModelGateway(config)


class FakeTransport:
    """Sustituye _post_json capturando la petición y devolviendo una respuesta fija."""

    def __init__(self, response: dict):
        self.response = response
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url: str, api_key: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
        self.calls.append((url, payload, headers or {}))
        return self.response


# ---------------------------------------------------------------------------
# client_for: resolución y degradación
# ---------------------------------------------------------------------------


def test_client_for_builds_clients_when_keys_present(monkeypatch):
    gw = make_gateway()
    env = {"AI_GATEWAY_API_KEY": "k1", "OPENCODE_API_KEY": "k2"}
    jev = gw.client_for("research-hypothesis", "evaluator", env=env)
    gen = gw.client_for("research-hypothesis", "generative", env=env)
    assert isinstance(jev, JevClient) and jev.model_id == "typesafe-ai/jev"
    assert isinstance(gen, OpenAICompatClient) and gen.model_id == "gpt-6-luna"
    assert gen.base_url == "https://opencode.ai/zen/go/v1"


def test_client_for_protocol_dispatch():
    from tf.gateway import OpenAIResponsesClient

    config = GatewayConfig.model_validate(
        {
            "models": {
                "gpt": {
                    "kind": "generative",
                    "id": "gpt-6-luna",
                    "provider": "opencode-go",
                    "protocol": "responses",
                    "endpoint": "https://opencode.ai/zen/go/v1",
                    "api_key_env": "OPENCODE_API_KEY",
                },
            },
            "agents": {"agent-x": {"generative": "gpt"}},
        }
    )
    gw = ModelGateway(config)
    client = gw.client_for("agent-x", "generative", env={"OPENCODE_API_KEY": "k"})
    assert isinstance(client, OpenAIResponsesClient)


def test_client_for_returns_none_without_key_or_provider():
    gw = make_gateway()
    assert gw.client_for("research-hypothesis", "evaluator", env={}) is None
    assert gw.client_for("research-hypothesis", "generative", env={}) is None
    # Modelo declarado sin proveedor real: ruta determinista.
    assert gw.client_for("plain-agent", "generative", env={"OPENCODE_API_KEY": "k"}) is None


# ---------------------------------------------------------------------------
# Clientes HTTP: forma de la petición y del parseo
# ---------------------------------------------------------------------------


def test_jev_client_request_and_answers(monkeypatch):
    fake = FakeTransport({"answers": {"escalate": {"type": "noul", "noul": 0.93}}})
    monkeypatch.setattr("tf.gateway._post_json", fake)
    jev = JevClient(model_id="typesafe-ai/jev", api_key="k")
    answers = jev.evaluate("mercado en caída", {"escalate": {"type": "noul", "instructions": "¿escalar?"}})
    url, payload, headers = fake.calls[0]
    assert url == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert payload["model"] == "typesafe-ai/jev"
    assert answers["escalate"]["noul"] == 0.93


def test_opencode_clients_send_session_header(monkeypatch):
    fake = FakeTransport({"answers": {}, "choices": [{"message": {"content": ""}}]})
    monkeypatch.setattr("tf.gateway._post_json", fake)
    jev = JevClient(model_id="jev-1.13", api_key="k", base_url="https://opencode.ai/zen/v1")
    jev.evaluate("estado", {"q": {"type": "noul", "instructions": "¿?"}})
    gen = OpenAICompatClient(model_id="glm-5.3-flash", api_key="k", base_url="https://opencode.ai/zen/go/v1")
    gen.complete("s", "u")
    for url, _payload, headers in fake.calls:
        assert headers["x-opencode-session"]


def test_responses_client_request_and_content(monkeypatch):
    fake = FakeTransport(
        {"output": [{"type": "message", "content": [{"type": "output_text", "text": "[{\"hypothesis\": \"h\"}]"}]}]}
    )
    monkeypatch.setattr("tf.gateway._post_json", fake)
    gen = OpenAIResponsesClient(model_id="gpt-6-luna", api_key="k", base_url="https://opencode.ai/zen/go/v1")
    out = gen.complete(system="s", user="u")
    url, payload, headers = fake.calls[0]
    assert url == "https://opencode.ai/zen/go/v1/responses"
    assert payload["model"] == "gpt-6-luna"
    assert "temperature" not in payload  # gpt-6-luna lo rechaza vía Responses
    assert headers["x-opencode-session"]
    assert json.loads(out) == [{"hypothesis": "h"}]


def test_generative_client_request_and_content(monkeypatch):
    fake = FakeTransport({"choices": [{"message": {"content": "[{\"hypothesis\": \"h\"}]"}}]})
    monkeypatch.setattr("tf.gateway._post_json", fake)
    gen = OpenAICompatClient(model_id="gpt-6-luna", api_key="k", base_url="https://opencode.ai/zen/go/v1")
    out = gen.complete(system="s", user="u")
    url, payload, headers = fake.calls[0]
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert payload["model"] == "gpt-6-luna"
    assert json.loads(out) == [{"hypothesis": "h"}]


def test_post_json_surfaces_http_error_body(monkeypatch):
    import urllib.error

    from tf import gateway

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error":{"message":"model not enabled for this plan"}}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="403.*model not enabled"):
        gateway._post_json("https://x/v1/chat/completions", "k", {}, timeout=5)


# ---------------------------------------------------------------------------
# ResearchLLMAgent: filtros y fallback, todo con clientes falsos
# ---------------------------------------------------------------------------

LLM_RESPONSE = json.dumps(
    [
        {"hypothesis": "Momentum 60d persiste por flujo institucional.", "spec": {"type": "momentum", "params": {"lookback": 60, "threshold": 0.02}}},
        {"hypothesis": "Cruce rápido lento en tendencia.", "spec": {"type": "sma_cross", "params": {"fast_window": 60, "slow_window": 20}}},  # spec inválido
        {"hypothesis": "Rupturas continúan.", "spec": {"type": "breakout", "params": {"lookback": 50, "exit_buffer": 0.05}}},
    ]
)


class FakeGenerative:
    def __init__(self, content: str):
        self.content = content

    def complete(self, system: str, user: str, temperature: float = 0.7) -> str:
        return self.content


class FakeJev:
    def __init__(self, noul: float):
        self.noul = noul
        self.states: list[str] = []

    def evaluate(self, state, questions):
        self.states.append(state)
        return {name: {"type": "noul", "noul": self.noul} for name in questions}


def make_llm_agent(generative, jev, audit, bus, broker, memory=None):
    from tf.research_llm import ResearchLLMAgent

    return ResearchLLMAgent(
        gateway=make_gateway(),
        generative=generative,
        jev=jev,
        name="research-hypothesis",
        role="hypothesis",
        bus=bus,
        broker=broker,
        audit=audit,
        memory=memory,
    )


def make_deps():
    from tf.audit import SqliteAuditLog
    from tf.bus import InMemoryBus
    from tf.permissions import PermissionBroker
    from pathlib import Path

    bus = InMemoryBus()
    audit = SqliteAuditLog()
    broker = PermissionBroker.from_yaml(Path(__file__).parent.parent / "config" / "guardrails.yaml", audit=audit)
    return bus, audit, broker


def test_llm_agent_publishes_valid_and_jev_accepted():
    bus, audit, broker = make_deps()
    jev = FakeJev(noul=0.9)
    agent = make_llm_agent(FakeGenerative(LLM_RESPONSE), jev, audit, bus, broker)
    out = agent.generate()
    assert len(out) == 2  # el spec inválido no se publica
    assert all(env.type == "strategy.proposal.v1" for env, _ in out)
    assert len(jev.states) == 2  # Jev solo vio los specs válidos
    events = [e["event_type"] for e in audit.entries()]
    assert "research.proposal_skipped" in events


def test_llm_agent_rejects_low_jev_scores():
    bus, audit, broker = make_deps()
    agent = make_llm_agent(FakeGenerative(LLM_RESPONSE), FakeJev(noul=0.1), audit, bus, broker)
    assert agent.generate() == []
    reasons = [e["payload"]["reason"] for e in audit.entries() if e["event_type"] == "research.proposal_skipped"]
    assert any("jev" in r for r in reasons)


def test_llm_agent_without_evaluator_does_not_block_but_audits():
    bus, audit, broker = make_deps()
    agent = make_llm_agent(FakeGenerative(LLM_RESPONSE), None, audit, bus, broker)
    out = agent.generate()
    assert len(out) == 2
    failovers = [e for e in audit.entries() if e["event_type"] == "model.failover"]
    assert any("Jev" in e["payload"]["reason"] for e in failovers)


def test_llm_agent_degrades_when_jev_endpoint_fails():
    bus, audit, broker = make_deps()

    class BrokenJev:
        def evaluate(self, state, questions):
            raise RuntimeError("HTTP 402 de https://opencode.ai/zen/v1/systemone: Insufficient account funds")

    agent = make_llm_agent(FakeGenerative(LLM_RESPONSE), BrokenJev(), audit, bus, broker)
    out = agent.generate()
    assert len(out) == 2  # el fallo del evaluador no tumba el pipeline
    failovers = [e for e in audit.entries() if e["event_type"] == "model.failover"]
    assert any("402" in e["payload"]["reason"] for e in failovers)


def test_llm_agent_without_generative_falls_back_to_template():
    bus, audit, broker = make_deps()
    agent = make_llm_agent(None, None, audit, bus, broker)
    out = agent.generate()
    # Plantilla determinista: 5 hipótesis semilla.
    assert len(out) == 5
    failovers = [e for e in audit.entries() if e["event_type"] == "model.failover"]
    assert any("plantilla determinista" in e["payload"]["reason"] for e in failovers)


def test_llm_agent_audits_non_json_response():
    bus, audit, broker = make_deps()
    agent = make_llm_agent(FakeGenerative("no soy json"), None, audit, bus, broker)
    assert agent.generate() == []
    assert any(e["event_type"] == "model.output_invalid" for e in audit.entries())


def test_pipeline_runner_uses_llm_agent_with_gateway():
    from tf.pipeline import PipelineRunner
    from tf.validation import ValidationPolicy

    bus, audit, broker = make_deps()
    runner = PipelineRunner(bus, broker, audit, policy=ValidationPolicy(min_trades=30), gateway=make_gateway())
    agent = runner._hypothesis_agent()
    from tf.research_llm import ResearchLLMAgent

    assert isinstance(agent, ResearchLLMAgent)
    # Sin credenciales en el entorno, su generate() degrada a plantilla.
    assert len(agent.generate()) == 5


def test_config_models_yaml_is_valid():
    from pathlib import Path

    gw = ModelGateway.from_yaml(Path(__file__).parent.parent / "config" / "models.yaml")
    model = gw.resolve("research-hypothesis", "evaluator")
    assert model.id == "jev-1.13"
    assert model.api_key_env == "OPENCODE_API_KEY"  # una sola credencial para todo
