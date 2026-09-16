"""The three agents of the onboarding example.

One credential each, none of them holding a model. That is the whole shape of
the thing, and it is a deployment decision rather than a protocol one — LIP
sees three agents and does not know the difference.

Why three and not two is the part worth noticing. An agent that could both
read the template and send the mail would hold ``doc:read`` and ``email:send``
in one process, which is the composition this protocol exists to govern,
rebuilt where no coordinator can see it. Splitting them keeps the combination
in the plan, where ``negotiation_acceptance`` can judge it.

Run them with ``python -m agentic_bus.agents.examples.onboarding.run_agents``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from agentic_bus import ScopedResource, remember
from agentic_bus.agents.base.agent import BaseAgent
from agentic_bus.core.registry.capability_registry import AgentCapability

# ---------------------------------------------------------------------------
# Stand-ins for the real systems.
#
# Each is what the agent's credential would reach. They are deliberately dumb:
# the example is about who may call them and when, not about what they do.
# ---------------------------------------------------------------------------

_CUSTOMERS = [
    {"id": 1, "nome": "Marta Ribeiro", "email": "marta@acme.example", "criado_em": "ontem"},
    {"id": 2, "nome": "Caio Duarte", "email": "caio@globex.example", "criado_em": "ontem"},
    {"id": 3, "nome": "Lia Antunes", "email": "lia@initech.example", "criado_em": "ontem"},
    {"id": 4, "nome": "Rafael Souza", "email": "rafael@interno.local", "criado_em": "ontem"},
]

_TEMPLATE = {
    "doc_id": "welcome-pt-br",
    "titulo": "Bem-vindo à Perihelion",
    "corpo": "Olá {nome}, que bom ter você aqui. Sua conta já está ativa.",
    # Sensitivity, not destination. A welcome template is written to be read by
    # customers, so it is public — which is exactly why the invariant that
    # refuses restricted material leaving the tenant does not fire on it.
    "classificacao": "Publico",
}


class _FakeCRM:
    async def buscar(self, *, cadastrado_desde: str | None = None) -> list[dict]:
        await asyncio.sleep(0.05)
        return list(_CUSTOMERS)


class _FakeSharePoint:
    async def get_doc(self, doc_id: str) -> dict:
        await asyncio.sleep(0.05)
        return dict(_TEMPLATE)


class _FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.sleep(0.01)
        self.sent.append({"to": to, "subject": subject})


# ---------------------------------------------------------------------------
# Artifacts.
#
# `output_model` derives the JSON Schema the coordinator validates a
# `complete` against (RFC 0002). Each agent reports a summary; the working
# data travels through session memory, which is what the next step reads.
# ---------------------------------------------------------------------------


class ClienteRef(BaseModel):
    memory_key: str = Field(description="Where the rows were staged")
    row_count: int
    columns: list[str]


class TemplateRef(BaseModel):
    memory_key: str = Field(description="Where the template was staged")
    doc_id: str
    classificacao: str = Field(description="Sensitivity, per the source system")


class EnvioResumo(BaseModel):
    enviados: int
    destinatarios: list[str] = Field(description="Addresses actually written to")


# ---------------------------------------------------------------------------


class CRMAgent(BaseAgent):
    """Reads the customer base. Holds ``crm:read`` and nothing else."""

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="crm-reader",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Consulta a base de clientes do CRM: busca por período de "
                "cadastro, por segmento e por status de assinatura."
            ),
        )
        # The credential is reachable only through the scope check, and the
        # factory does not run until that check passes — a scope never granted
        # is a connection never opened.
        self.crm = ScopedResource("crm:read", _FakeCRM)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="crm.buscar_clientes",
                description=(
                    "Busca clientes no CRM por período de cadastro. Deixa as "
                    "linhas na memória da sessão e devolve um resumo."
                ),
                required_scopes=["crm:read"],
                supported_data_domains=["crm", "customer"],
                operational_constraints={"max_rows": 50_000},
                expected_artifacts=["cliente_ref"],
                estimated_cost=0.01,
                estimated_latency=1.0,
                output_model=ClienteRef,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        crm = self.crm.get()

        filtros = context.get("filtros") or {}
        desde = filtros.get("cadastrado_desde") or str(date.today() - timedelta(days=1))
        linhas = await crm.buscar(cadastrado_desde=desde)

        key = f"{self.agent_id}.clientes"
        remember(key, linhas)

        return ClienteRef(
            memory_key=key,
            row_count=len(linhas),
            columns=list(linhas[0].keys()) if linhas else [],
        ).model_dump()


class SharePointAgent(BaseAgent):
    """Reads documents. Holds ``doc:read`` and nothing else."""

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="sharepoint-reader",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Busca documentos no SharePoint: modelos de e-mail, políticas "
                "internas e material de comunicação, com a classificação de "
                "sensibilidade que o sistema de origem atribuiu."
            ),
        )
        self.sharepoint = ScopedResource("doc:read", _FakeSharePoint)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="doc.buscar_modelo",
                description=(
                    "Busca um modelo de documento pelo identificador e o deixa "
                    "na memória da sessão, com a classificação de origem."
                ),
                required_scopes=["doc:read"],
                supported_data_domains=["document", "communication"],
                expected_artifacts=["template_ref"],
                estimated_cost=0.005,
                estimated_latency=0.5,
                output_model=TemplateRef,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        sharepoint = self.sharepoint.get()

        doc_id = (context.get("modelo") or {}).get("doc_id", "welcome-pt-br")
        doc = await sharepoint.get_doc(doc_id)

        key = f"{self.agent_id}.modelo"
        remember(key, doc)

        return TemplateRef(
            memory_key=key,
            doc_id=doc["doc_id"],
            classificacao=doc["classificacao"],
        ).model_dump()


class EmailAgent(BaseAgent):
    """Sends mail. Holds ``email:send`` and nothing else — the egress point.

    It reads neither the CRM nor SharePoint. Everything it acts on arrives
    from the steps before it, which is what keeps the combination visible to
    the coordinator instead of hidden inside one agent.
    """

    def __init__(self, coordinator_uri: str = "ws://localhost:8765") -> None:
        super().__init__(
            agent_id="email-sender",
            coordinator_uri=coordinator_uri,
            version="1.0.0",
            semantic_description=(
                "Envia e-mail transacional a partir de um modelo e de uma "
                "lista de destinatários produzidos por passos anteriores."
            ),
        )
        self.mailer = ScopedResource("email:send", _FakeMailer)

    def capabilities(self) -> list[AgentCapability]:
        return [
            AgentCapability(
                capability_id="email.enviar_modelo",
                description=(
                    "Envia um modelo de e-mail para uma lista de destinatários, "
                    "personalizando por destinatário."
                ),
                required_scopes=["email:send"],
                supported_data_domains=["communication"],
                operational_constraints={"max_recipients": 5_000},
                expected_artifacts=["envio_resumo"],
                estimated_cost=0.02,
                estimated_latency=2.0,
                output_model=EnvioResumo,
            ),
        ]

    async def execute_task(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        mailer = self.mailer.get()

        # What the previous steps produced. `prior_results` carries the
        # artifacts of the steps before this one — which is how a result
        # reaches the agent that consumes it today; the coordinator also
        # builds a per-agent `memory_snapshot`, but `_handle_execute` does
        # not yet hand it to `execute_task`.
        prior = payload.get("prior_results") or {}
        clientes = _find(prior, "row_count", fallback=_CUSTOMERS)
        modelo = _find(prior, "doc_id", fallback=_TEMPLATE)

        rows = clientes if isinstance(clientes, list) else _CUSTOMERS
        corpo = (modelo or _TEMPLATE).get("corpo", _TEMPLATE["corpo"])
        titulo = (modelo or _TEMPLATE).get("titulo", _TEMPLATE["titulo"])

        for row in rows:
            await mailer.send(
                to=row["email"],
                subject=titulo,
                body=corpo.format(nome=row.get("nome", "")),
            )

        return EnvioResumo(
            enviados=len(mailer.sent),
            destinatarios=[m["to"] for m in mailer.sent],
        ).model_dump()


def _find(prior: dict, marker: str, *, fallback: Any) -> Any:
    """Pick out of ``prior_results`` the artifact carrying *marker*.

    Steps are keyed by however the plan named them, so the consumer looks for
    the shape it needs rather than for a key it has to guess.
    """
    for value in prior.values():
        if isinstance(value, dict) and marker in value:
            return value
    return fallback
