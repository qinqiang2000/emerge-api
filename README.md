# emerge

> Documents in. APIs emerge. They get better as you correct them.

A Software 3.0 document API platform. Drop documents into a project, talk to an agent, correct what's wrong, and get a stable extraction API.

- **Lab side**: chat-driven via `claude_agent_sdk`. Three skills: `emerge-extractor`, `emerge-autoresearch`, `emerge-publish`.
- **Prod side**: deterministic fast-path that loads a frozen version and calls the provider directly. Never invokes the agent.
- **Storage**: project = folder. No database.
- **Extract LLM**: any provider (Anthropic / OpenAI / Gemini), per-project.

## Design

- Implementation plans under `docs/superpowers/plans/`

## Status

Design phase. Implementation kicks off with M1 (walking skeleton).
