# provider_adapter.py
# THE PROVIDER ADAPTER BASE
#
# Responsibility:
#   Defines the contract that every model provider adapter must implement.
#   Concrete adapters (e.g. ollama_adapter.py, openai_adapter.py) inherit from this.
#
# Expected contents:
#   - BaseProviderAdapter abstract class or protocol with:
#       name            — provider identifier (e.g. "ollama", "openai")
#       complete(prompt, model, params) — sends prompt, returns completion
#       is_available()  — health check for the provider
#   - Shared error types and retry logic
#
# What does NOT belong here:
#   - Provider-specific API calls (each provider gets its own file)
#   - Routing logic (that belongs in model_router.py)
#   - Embedding adapters (that belongs in rag/)
