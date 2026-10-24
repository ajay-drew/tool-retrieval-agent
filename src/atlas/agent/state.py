from typing import NotRequired

from langchain.agents.middleware.types import AgentState


class AtlasState(AgentState):
    found_tools: NotRequired[list[str]]
    allowed_tools: NotRequired[list[str]]
    last_retrieval: NotRequired[dict]
