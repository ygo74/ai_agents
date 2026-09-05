"""Adapter between the repository abstractions and Microsoft Agent Framework.

Only this package imports ``agent_framework``. It translates types and wires
middleware; it holds no business rule. Swapping it for a LangChain or CrewAI
adapter must be enough to run the very same agent definition and the very same
skills.

Targets the GA API of Microsoft Agent Framework 1.17: ``Agent``,
``AgentResponse``, ``Message``, ``Content``, ``FunctionTool`` and
``AgentSession``.
"""

from __future__ import annotations
