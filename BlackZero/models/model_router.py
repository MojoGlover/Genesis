# model_router.py
# THE MODEL ROUTER
#
# Responsibility:
#   Routes generation requests to the correct model provider based on
#   configuration, task type, or cost/performance tradeoffs.
#
# Expected contents:
#   - complete(prompt, config) — main generation interface
#   - Provider selection logic (e.g. Ollama, OpenAI, Anthropic, local)
#   - Model selection per task type (fast model for simple tasks, large model for complex)
#   - Fallback logic if a provider is unavailable
#   - Abstraction so provider can be swapped without changing callers
#
# What does NOT belong here:
#   - Provider-specific implementation details (each provider gets its own adapter)
#   - Training data or prompt experiments
#   - Embedding logic (that belongs in rag/embedding_router.py)
