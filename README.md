This repository is an enterprise AI agent laboratory.

Its purpose is to evaluate agentic AI frameworks and establish the technical foundations for a future enterprise agent platform.

The first frameworks evaluated are:

Microsoft Agent Framework
LangChain
CrewAI

The repository implements several enterprise agents, including:

Mail Agent
Memory Agent
Jira Agent
Confluence Agent
On-Prem RAG Agent
Internet Research Agent
IT Project Agent

Agents do not implement direct integrations with enterprise systems.

All interactions with external systems must happen through tools exposed by MCP servers.

Agents may use reusable Skills to perform domain-specific reasoning and processing.

The same domain Skills and MCP tools must be reusable across the different agent frameworks wherever technically possible.

The purpose is to compare frameworks rather than to create three independent implementations of the same business logic.