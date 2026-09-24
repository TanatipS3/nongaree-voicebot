from typing import Annotated, Literal, NotRequired, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    query: str
    context: str
    answer: str
    emotion: str
    route: Literal["direct", "rag", "out_of_scope", "curated"]
    # Citation records for the chunks behind `context`; empty on non-rag routes.
    sources: list
    # Set by parallel_node when the LLM follow-up classifier confirmed this question depends
    # on the previous turn; tells retrieval to widen even without an anaphora marker.
    is_followup: NotRequired[bool]
