# AgentScope Voice Discovery

A Pathwise-built voice-first discovery prototype powered by AgentScope.

## Overview

AgentScope Voice Discovery is a Pathwise-built experiment for exploring voice-first agent discovery experiences. It uses AgentScope’s agent and realtime voice capabilities to prototype conversational discovery flows where users can speak naturally, receive intelligent responses, and move through agent-powered exploration with less friction.

This is a focused project that uses AgentScope to test how voice interaction can support natural, conversational discovery. It is not the official AgentScope framework itself. AgentScope provides the agent framework used by the project, supporting agent reasoning, tool use, workflow orchestration, and voice-related capabilities.

## Why Pathwise Built This

Pathwise built this to explore a more natural way for users to discover information, services, workflows, or recommendations. Voice is often faster and more intuitive than typing, especially when the user does not yet know the exact keywords or path. The project tests whether an agent can guide discovery through conversation instead of static navigation.

Traditional discovery flows often depend on search boxes, filters, forms, and rigid navigation. These work when users know exactly what they want, but they create friction when users are exploring. This project explores a voice-first alternative where the user can describe intent in plain language and the agent can help clarify, narrow, and guide the discovery process.

## What This Project Explores

- Natural voice input for discovery
- Conversational clarification
- Agent-guided exploration
- Realtime response loops
- Future Pathwise experience patterns

## How It Works

1. User speaks a request.
2. Voice input is captured.
3. AgentScope-powered agent interprets the request.
4. Agent asks follow-up questions or provides a useful response.
5. The user continues the discovery flow through conversation.

## Architecture

```text
User Voice Input
    ↓
Voice Interface
    ↓
AgentScope Agent Layer
    ↓
Discovery Logic / Tools
    ↓
Response Generation
    ↓
Voice or Text Output
```

## Getting Started

TODO: Add exact install command after dependencies are finalized.
TODO: Add required environment variables.
TODO: Add local run command.
TODO: Add demo recording or screenshot.
TODO: Document project structure after implementation files are added.

## Documentation

- [AgentScope Tutorial](https://doc.agentscope.io/tutorial/)
- [AgentScope FAQ](https://doc.agentscope.io/tutorial/faq.html)
- [AgentScope API Docs](https://doc.agentscope.io/api/agentscope.html)

## License

AgentScope is released under Apache License 2.0.
