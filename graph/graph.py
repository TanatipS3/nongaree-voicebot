from langgraph.graph import END, START, StateGraph

from graph.nodes import curated_node, generate_node, out_of_scope_node, parallel_node
from graph.state import AgentState

builder = StateGraph(AgentState)

builder.add_node("parallel", parallel_node)
builder.add_node("generate", generate_node)
builder.add_node("out_of_scope", out_of_scope_node)
builder.add_node("curated", curated_node)

builder.add_edge(START, "parallel")
builder.add_conditional_edges(
    "parallel",
    lambda state: state["route"],
    {
        "direct": "generate",
        "rag": "generate",
        "out_of_scope": "out_of_scope",
        "curated": "curated",
    },
)
builder.add_edge("generate", END)
builder.add_edge("out_of_scope", END)
builder.add_edge("curated", END)

compiled_graph = builder.compile()
