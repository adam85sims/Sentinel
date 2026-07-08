"""Sentinel framework adapters.

Each adapter bridges sentinel's mock tool layer to a specific agent framework,
enabling behavioral testing without modifying the agent's source code.

Available adapters:
    - langchain: LangChain agents (BaseTool, Runnable)
    - crewai: CrewAI agents (BaseTool, @tool)
    - openai: OpenAI Agents SDK (FunctionTool, function_tool)
    - generic: Any callable (hook-based, framework-agnostic)
"""
