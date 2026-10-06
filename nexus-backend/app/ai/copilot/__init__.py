"""NEXUS FC AI Copilot tool layer (Phase 09A).

Provider-independent tool contracts and a governed registry. The LLM
never touches the database, filesystem, Qdrant, or application
internals — it may only invoke registered tools, and every invocation
flows through ``ToolRegistry.execute`` with a server-side actor.
"""
