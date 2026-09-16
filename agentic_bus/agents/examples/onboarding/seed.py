"""Seed the vocabulary, the bindings and the policies for the example.

Three things, and keeping them apart is the point:

**Catalogue** — the names this coordinator recognises. A property of the
deployment, not of any agent. An agent that declares a name outside it is not
refused; the name is recorded as a request for an operator to look at, and the
refusal carries the catalogue back so the implementer learns the right one.

**Bindings** — which of those names a capability actually holds. *This* is the
authority: an agent's declaration never is. A capability with no binding
declares whatever it likes and holds nothing.

**IBAC rules** — what is forbidden, named as combinations rather than
enumerated as a matrix. Two rules cover six cells here.

Usage::

    python -m agentic_bus.agents.examples.onboarding.seed
"""

from __future__ import annotations

import logging
import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


SCOPES: list[tuple[str, str]] = [
    ("crm:read", "Ler a base de clientes do CRM"),
    ("doc:read", "Ler documentos e modelos no repositório"),
    ("email:send", "Enviar e-mail em nome da organização"),
]

#: capability -> scopes. The binding is the authority.
BINDINGS: list[tuple[str, str, list[str]]] = [
    ("crm-reader", "crm.buscar_clientes", ["crm:read"]),
    ("sharepoint-reader", "doc.buscar_modelo", ["doc:read"]),
    ("email-sender", "email.enviar_modelo", ["email:send"]),
]


RULES: list[dict] = [
    {
        "rule_id": "onboarding-deny-destructive",
        "name": "Recusar intenções destrutivas",
        "description": (
            "Uma intenção que peça para apagar, purgar ou zerar registros é "
            "recusada antes de qualquer agente ser consultado. Nada adiante "
            "ganha a chance de interpretá-la com boa vontade."
        ),
        "priority": 10,
        "action": "deny",
        "evaluation_points": ["intent_admission"],
        "conditions": {
            "intent_keywords": ["delete", "apagar", "purgar", "drop table", "zerar"],
        },
    },
    {
        "rule_id": "onboarding-bulk-export-needs-a-person",
        "name": "Exportação em massa exige confirmação humana",
        "description": (
            "Extrair a base de clientes para fora do fluxo de trabalho — CSV, "
            "planilha, dump — exige que uma pessoa confirme. Enviar "
            "comunicação a esses clientes não é exportação: o destinatário é "
            "o titular do próprio dado, e tratar os dois casos como o mesmo "
            "bloquearia o trabalho legítimo junto com o risco."
        ),
        "priority": 20,
        "action": "deny",
        "evaluation_points": ["intent_admission"],
        "conditions": {
            "intent_patterns": [r"(?i)\b(export\w*|csv|planilha|dump)\b"],
            "require_human_approval": True,
        },
    },
    {
        "rule_id": "onboarding-cap-the-composition",
        "name": "Limitar o tamanho da composição",
        "description": (
            "Um plano de onboarding envolve ler clientes, buscar um modelo e "
            "enviar. Precisar de muito mais que isso quer dizer que a "
            "intenção foi entendida de outro jeito — e a hora de notar é "
            "antes de executar, não depois."
        ),
        "priority": 30,
        "action": "deny",
        "evaluation_points": ["negotiation_acceptance"],
        "conditions": {"max_agents": 4},
    },
]


def main() -> None:
    from agentic_bus.core.persistence.database import init_db
    from agentic_bus.core.persistence.ibac_repository import IBACRuleRepository
    from agentic_bus.core.persistence.scope_repository import ScopeRepository

    init_db()

    scopes = ScopeRepository()
    # add_scope returns False when the name is already catalogued, so seeding
    # is re-runnable and the count stays honest on the second pass.
    added = sum(
        scopes.add_scope(name, description=description, created_by="onboarding-seed")
        for name, description in SCOPES
    )

    bound = 0
    for agent_id, capability, names in BINDINGS:
        bound += len(scopes.bind(agent_id, capability, names, bound_by="onboarding-seed"))

    rules = IBACRuleRepository()
    created = skipped = 0
    for rule in RULES:
        try:
            rules.add(
                rule["rule_id"],
                rule["name"],
                description=rule["description"],
                priority=rule["priority"],
                action=rule["action"],
                evaluation_points=rule["evaluation_points"],
                conditions=rule["conditions"],
                created_by="onboarding-seed",
            )
            created += 1
        except ValueError:
            skipped += 1

    print()
    print(f"  catálogo : {added} escopo(s) adicionado(s), {len(SCOPES) - added} já presente(s)")
    print(f"  bindings : {bound} concessão(ões) nova(s)")
    print(f"  políticas: {created} criada(s), {skipped} já presente(s)")
    print()
    print("  Confira com:  agbus scope granted crm-reader")
    print()


if __name__ == "__main__":
    main()
