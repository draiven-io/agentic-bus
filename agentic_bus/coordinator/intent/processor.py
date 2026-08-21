"""Intent admission and decomposition.

When a requester submits an ``intent`` message the coordinator must:
1. Validate the intent via IBAC (intent admission).
2. Decompose the intent into sub-intentions if needed (§5.1.4 – Composable
   Intent Resolution).
3. Discover eligible agents via the semantic adjudicator.

Intent decomposition leverages LangChain to break a high-level objective into
actionable sub-intents that can be individually matched and negotiated.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from agentic_bus.core.llm import get_llm
from agentic_bus.core.protocol.envelope import IntentPayload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM-based intent decomposition
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """\
You are the intent decomposition engine of the Agentic Bus Protocol.
Given a high-level user intent and its context, decompose it into a list of
concrete sub-intents that can each be fulfilled by a single agent capability.

Return a JSON object with the following structure:
{{
  "sub_intents": [
    {{
      "id": "<short unique id>",
      "description": "<what this sub-intent achieves>",
      "dependencies": ["<id of sub-intent that must complete first>"],
      "required_domains": ["<data domain needed>"],
      "constraints": {{}}
    }}
  ],
  "rationale": "<brief explanation of the decomposition>"
}}

Only decompose if the intent genuinely requires multiple capabilities.
If the intent is atomic, return a single sub-intent.
"""


class IntentProcessor:
    """Handles intent admission, validation, and decomposition."""

    def __init__(self, llm: BaseChatModel | None = None):
        self._llm = llm or get_llm()
        self._prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _DECOMPOSE_SYSTEM),
                ("human", "Intent: {intent_text}\nContext: {context}"),
            ]
        )
        self._parser = JsonOutputParser()
        self._chain = self._prompt | self._llm | self._parser

    async def decompose(self, intent: IntentPayload) -> dict[str, Any]:
        """Decompose a high-level intent into sub-intents.

        Returns a dict with ``sub_intents`` (list) and ``rationale`` (str).
        """
        result = await self._chain.ainvoke(
            {
                "intent_text": intent.intent_text,
                "context": str(intent.context),
            }
        )
        logger.info(
            "Decomposed intent into %d sub-intents: %s",
            len(result.get("sub_intents", [])),
            result.get("rationale", ""),
        )
        return result
