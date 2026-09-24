# Project Structure

This repository combines a Python LiveKit voice agent, a LangGraph/RAG backend, and a Next.js frontend.

## Top-Level Layout

```text
app/                         Next.js App Router pages and API routes
components/                  React UI components
graph/                       LangGraph nodes, routing, retrieval, and shared graph state
public/                      Static frontend assets
docs/                        Handoff, QA, and project documentation
agent.py                     LiveKit voice agent entrypoint
benchmark.py                 Local latency benchmark utility
local_bot_demo.py            Standalone local Python demo
rag_node_test.py             Local RAG/retriever smoke test
open_*.command               macOS launch helpers
requirements.txt             Python dependencies
package.json                 Frontend scripts and dependencies
```

## Main Runtime Flows

### Voice Agent

```text
agent.py
  -> graph/graph.py
  -> graph/nodes.py
  -> graph/retriever.py
```

The voice path is optimized for short spoken answers. Long or structured information should be shown in the detailed preview instead of being read aloud.

### Frontend

```text
app/page.tsx
  -> components/VoiceRoom.tsx
  -> components/LumoFace.tsx
```

`VoiceRoom` owns the LiveKit connection, receives data-channel events, and renders the detailed preview.

### Detailed Preview

```text
graph/nodes.py
  TEXT_SYSTEM_PROMPT

components/VoiceRoom.tsx
  renderMarkdownPreview()
```

The text/detail path is designed for structured UI output such as calculation tables, deduction tables, condition cards, and follow-up prompts.

## Documentation

```text
docs/DETAILED_PREVIEW_HANDOFF.md
docs/QA_QUERY_EXPECTATIONS.md
docs/PROJECT_STRUCTURE.md
```

Use `QA_QUERY_EXPECTATIONS.md` when reviewing output quality with a supervisor. It includes copy/paste queries and expected answer shapes.

## Generated Files

The repository should not commit generated files such as:

```text
__pycache__/
*.pyc
.next/
SCR-*.png
```

These are ignored by `.gitignore`.
