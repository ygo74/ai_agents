"""LangChain / LangGraph adapter for the AI Agent Lab agents.

This distribution holds everything that knows LangChain exists, and nothing
else: the chat model factory, the reasoning port, the skill-to-tool adapter and
the translation between the domain confirmation vocabulary and the framework's
human-in-the-loop interrupts.

Domain models, skills and MCP contracts stay in the agent distributions, shared
with the Microsoft Agent Framework adapter. That is what makes a comparison
between the two frameworks fair: the business logic is written once, never
ported.

The package is called ``ai_agent_lab.langgraph`` while the framework it adapts is
called ``langgraph``. Python 3 resolves imports absolutely, so a module in here
asking for ``langgraph`` gets the third-party package rather than itself; a test
in ``tests/architecture`` pins that, because getting it wrong would be silent.
"""
