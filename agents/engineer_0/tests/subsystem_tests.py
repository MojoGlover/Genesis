# subsystem_tests.py
# BLACKZERO SUBSYSTEM INTERFACE TESTS
#
# Responsibility:
#   Verifies that every BlackZero subsystem file exports a real importable class
#   with the correct abstract methods defined. These tests ensure the template
#   is actually usable — not just a collection of comment stubs.
#
# Run with:
#   python -m pytest BlackZero/tests/subsystem_tests.py -v
#   or
#   python BlackZero/tests/subsystem_tests.py

import inspect
import sys


# ── Memory ──────────────────────────────────────────────────────────────────────

def test_memory_schema_imports():
    from BlackZero.memory.memory_schema import MemoryRecord, MemorySource
    assert MemoryRecord is not None
    assert MemorySource is not None


def test_memory_record_is_dataclass():
    import dataclasses
    from BlackZero.memory.memory_schema import MemoryRecord
    assert dataclasses.is_dataclass(MemoryRecord)


def test_memory_record_required_fields():
    from BlackZero.memory.memory_schema import MemoryRecord
    fields = {f.name for f in __import__('dataclasses').fields(MemoryRecord)}
    for required in ("id", "content", "source", "tags", "metadata", "created_at"):
        assert required in fields, f"MemoryRecord missing field: {required}"


def test_memory_record_is_expired():
    from BlackZero.memory.memory_schema import MemoryRecord
    r = MemoryRecord(content="test", ttl_seconds=None)
    assert r.is_expired() is False


def test_memory_record_to_dict():
    from BlackZero.memory.memory_schema import MemoryRecord
    r = MemoryRecord(content="hello")
    d = r.to_dict()
    assert isinstance(d, dict)
    assert d["content"] == "hello"
    assert "id" in d
    assert "created_at" in d


def test_memory_record_round_trip():
    from BlackZero.memory.memory_schema import MemoryRecord
    r1 = MemoryRecord(content="round trip test", tags=["a", "b"])
    r2 = MemoryRecord.from_dict(r1.to_dict())
    assert r2.id == r1.id
    assert r2.content == r1.content
    assert r2.tags == ["a", "b"]


def test_memory_manager_is_abstract():
    from BlackZero.memory.memory_manager import MemoryManager
    import abc
    assert inspect.isabstract(MemoryManager)


def test_memory_manager_abstract_methods():
    from BlackZero.memory.memory_manager import MemoryManager
    expected = {"add_memory", "get_memory", "search_memory", "delete_memory", "expire_old_memories"}
    abstract = set(MemoryManager.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"MemoryManager.{method} must be @abstractmethod"


def test_memory_manager_cannot_instantiate():
    from BlackZero.memory.memory_manager import MemoryManager
    try:
        MemoryManager()
        assert False, "Should not be able to instantiate abstract MemoryManager"
    except TypeError:
        pass


# ── Storage ─────────────────────────────────────────────────────────────────────

def test_sqlite_store_is_abstract():
    from BlackZero.storage.sqlite_store import SQLiteStore
    assert inspect.isabstract(SQLiteStore)


def test_sqlite_store_abstract_methods():
    from BlackZero.storage.sqlite_store import SQLiteStore
    expected = {"connect", "execute", "run", "insert", "close"}
    abstract = set(SQLiteStore.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"SQLiteStore.{method} must be @abstractmethod"


def test_vector_store_is_abstract():
    from BlackZero.storage.vector_store import VectorStore
    assert inspect.isabstract(VectorStore)


def test_vector_store_abstract_methods():
    from BlackZero.storage.vector_store import VectorStore
    expected = {"upsert", "search", "delete", "count"}
    abstract = set(VectorStore.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"VectorStore.{method} must be @abstractmethod"


# ── RAG ─────────────────────────────────────────────────────────────────────────

def test_embedding_router_is_abstract():
    from BlackZero.rag.embedding_router import EmbeddingRouter
    assert inspect.isabstract(EmbeddingRouter)


def test_embedding_router_abstract_methods():
    from BlackZero.rag.embedding_router import EmbeddingRouter
    expected = {"embed", "embed_batch", "dimensions"}
    abstract = set(EmbeddingRouter.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"EmbeddingRouter.{method} must be @abstractmethod"


def test_indexer_is_abstract():
    from BlackZero.rag.indexer import Indexer
    assert inspect.isabstract(Indexer)


def test_indexer_abstract_methods():
    from BlackZero.rag.indexer import Indexer
    expected = {"index_document", "remove_document"}
    abstract = set(Indexer.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"Indexer.{method} must be @abstractmethod"


def test_retriever_is_abstract():
    from BlackZero.rag.retriever import Retriever
    assert inspect.isabstract(Retriever)


def test_retriever_abstract_methods():
    from BlackZero.rag.retriever import Retriever
    assert "retrieve" in Retriever.__abstractmethods__


def test_retrieved_chunk_fields():
    from BlackZero.rag.retriever import RetrievedChunk
    chunk = RetrievedChunk(id="1", content="test content", score=0.95)
    assert chunk.id == "1"
    assert chunk.content == "test content"
    assert chunk.score == 0.95
    assert chunk.metadata == {}


def test_retriever_retrieve_as_text():
    """retrieve_as_text() is a concrete helper — verify it works with a minimal subclass."""
    from BlackZero.rag.retriever import Retriever, RetrievedChunk

    class _TestRetriever(Retriever):
        def retrieve(self, query, top_k=5):
            return [RetrievedChunk(id="a", content="chunk one", score=0.9)]

    r = _TestRetriever()
    text = r.retrieve_as_text("test query")
    assert "chunk one" in text
    assert "[1]" in text


# ── Tools ────────────────────────────────────────────────────────────────────────

def test_base_tool_is_abstract():
    from BlackZero.tools.base_tool import BaseTool
    assert inspect.isabstract(BaseTool)


def test_base_tool_abstract_methods():
    from BlackZero.tools.base_tool import BaseTool
    expected = {"name", "description", "run"}
    abstract = set(BaseTool.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"BaseTool.{method} must be @abstractmethod"


def test_tool_error_is_exception():
    from BlackZero.tools.base_tool import ToolError
    assert issubclass(ToolError, Exception)


def test_base_tool_validate_input():
    from BlackZero.tools.base_tool import BaseTool, ToolError

    class _TestTool(BaseTool):
        @property
        def name(self): return "test_tool"
        @property
        def description(self): return "A test."
        def run(self, input): return {"ok": True}

    tool = _TestTool()
    tool.validate_input({"query": "hello"}, ["query"])  # should not raise

    try:
        tool.validate_input({}, ["query"])
        assert False, "Should raise ToolError"
    except ToolError as e:
        assert "query" in str(e)


def test_tool_registry_register_and_get():
    from BlackZero.tools.base_tool import BaseTool
    from BlackZero.tools.tool_registry import ToolRegistry

    class _PingTool(BaseTool):
        @property
        def name(self): return "ping"
        @property
        def description(self): return "Returns pong."
        def run(self, input): return {"ok": True, "result": "pong"}

    registry = ToolRegistry()
    assert len(registry) == 0
    registry.register(_PingTool())
    assert len(registry) == 1
    assert "ping" in registry

    tool = registry.get("ping")
    assert tool is not None
    assert tool.name == "ping"


def test_tool_registry_run_tool():
    from BlackZero.tools.base_tool import BaseTool
    from BlackZero.tools.tool_registry import ToolRegistry

    class _EchoTool(BaseTool):
        @property
        def name(self): return "echo"
        @property
        def description(self): return "Echoes input."
        def run(self, input): return {"ok": True, "echo": input.get("msg", "")}

    registry = ToolRegistry()
    registry.register(_EchoTool())
    result = registry.run_tool("echo", {"msg": "hello"})
    assert result["echo"] == "hello"


def test_tool_registry_duplicate_raises():
    from BlackZero.tools.base_tool import BaseTool
    from BlackZero.tools.tool_registry import ToolRegistry

    class _T(BaseTool):
        @property
        def name(self): return "dup"
        @property
        def description(self): return "Duplicate."
        def run(self, input): return {"ok": True}

    registry = ToolRegistry()
    registry.register(_T())
    try:
        registry.register(_T())
        assert False, "Should raise ValueError on duplicate"
    except ValueError:
        pass


def test_tool_registry_unknown_tool_raises():
    from BlackZero.tools.base_tool import ToolError
    from BlackZero.tools.tool_registry import ToolRegistry
    registry = ToolRegistry()
    try:
        registry.run_tool("nonexistent", {})
        assert False, "Should raise ToolError for unknown tool"
    except ToolError:
        pass


def test_tool_registry_list_tools():
    from BlackZero.tools.base_tool import BaseTool
    from BlackZero.tools.tool_registry import ToolRegistry

    class _A(BaseTool):
        @property
        def name(self): return "alpha"
        @property
        def description(self): return "Alpha tool."
        def run(self, input): return {"ok": True}

    class _B(BaseTool):
        @property
        def name(self): return "beta"
        @property
        def description(self): return "Beta tool."
        def run(self, input): return {"ok": True}

    registry = ToolRegistry()
    registry.register(_B())
    registry.register(_A())
    tools = registry.list_tools()
    assert tools[0]["name"] == "alpha"   # sorted alphabetically
    assert tools[1]["name"] == "beta"


# ── Models ────────────────────────────────────────────────────────────────────────

def test_model_router_is_abstract():
    from BlackZero.models.model_router import ModelRouter
    assert inspect.isabstract(ModelRouter)


def test_model_router_abstract_methods():
    from BlackZero.models.model_router import ModelRouter
    expected = {"complete", "list_providers"}
    abstract = set(ModelRouter.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"ModelRouter.{method} must be @abstractmethod"


def test_generation_config_defaults():
    from BlackZero.models.model_router import GenerationConfig
    cfg = GenerationConfig()
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 1024
    assert cfg.model is None
    assert cfg.stop_sequences == []


def test_model_router_complete_with_system():
    from BlackZero.models.model_router import ModelRouter, GenerationConfig

    class _TestRouter(ModelRouter):
        def complete(self, prompt, config=None):
            cfg = config or GenerationConfig()
            prefix = f"[sys:{cfg.system_prompt}] " if cfg.system_prompt else ""
            return f"{prefix}{prompt}"
        def list_providers(self):
            return ["test"]

    router = _TestRouter()
    result = router.complete_with_system("You are helpful.", "Hello")
    assert "You are helpful" in result
    assert "Hello" in result


def test_provider_adapter_is_abstract():
    from BlackZero.models.provider_adapter import ProviderAdapter
    assert inspect.isabstract(ProviderAdapter)


def test_provider_adapter_abstract_methods():
    from BlackZero.models.provider_adapter import ProviderAdapter
    expected = {"name", "generate", "is_available"}
    abstract = set(ProviderAdapter.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"ProviderAdapter.{method} must be @abstractmethod"


def test_provider_error_is_exception():
    from BlackZero.models.provider_adapter import ProviderError
    assert issubclass(ProviderError, Exception)


# ── Diagnostics ──────────────────────────────────────────────────────────────────

def test_health_status_enum_values():
    from BlackZero.diagnostics.healthcheck import HealthStatus
    assert HealthStatus.HEALTHY.value == "HEALTHY"
    assert HealthStatus.DEGRADED.value == "DEGRADED"
    assert HealthStatus.UNHEALTHY.value == "UNHEALTHY"


def test_subsystem_result_ok():
    from BlackZero.diagnostics.healthcheck import SubsystemResult, HealthStatus
    r = SubsystemResult(name="test", status=HealthStatus.HEALTHY)
    assert r.ok() is True
    r2 = SubsystemResult(name="test", status=HealthStatus.UNHEALTHY, message="down")
    assert r2.ok() is False


def test_healthcheck_is_abstract():
    from BlackZero.diagnostics.healthcheck import HealthCheck
    assert inspect.isabstract(HealthCheck)


def test_healthcheck_abstract_methods():
    from BlackZero.diagnostics.healthcheck import HealthCheck
    expected = {
        "check_model_provider", "check_vector_store",
        "check_sqlite_store", "check_memory_manager", "check_tool_registry",
    }
    abstract = set(HealthCheck.__abstractmethods__)
    for method in expected:
        assert method in abstract, f"HealthCheck.{method} must be @abstractmethod"


def test_healthcheck_check_all_aggregates():
    from BlackZero.diagnostics.healthcheck import HealthCheck, HealthStatus, SubsystemResult

    class _AllHealthy(HealthCheck):
        def check_model_provider(self):
            return SubsystemResult("model_provider", HealthStatus.HEALTHY)
        def check_vector_store(self):
            return SubsystemResult("vector_store", HealthStatus.HEALTHY)
        def check_sqlite_store(self):
            return SubsystemResult("sqlite_store", HealthStatus.HEALTHY)
        def check_memory_manager(self):
            return SubsystemResult("memory_manager", HealthStatus.HEALTHY)
        def check_tool_registry(self):
            return SubsystemResult("tool_registry", HealthStatus.HEALTHY)

    report = _AllHealthy().check_all()
    assert report["overall"] == "HEALTHY"
    assert len(report["subsystems"]) == 5


def test_healthcheck_unhealthy_propagates():
    from BlackZero.diagnostics.healthcheck import HealthCheck, HealthStatus, SubsystemResult

    class _OneDown(HealthCheck):
        def check_model_provider(self):
            return SubsystemResult("model_provider", HealthStatus.UNHEALTHY, "timeout")
        def check_vector_store(self):
            return SubsystemResult("vector_store", HealthStatus.HEALTHY)
        def check_sqlite_store(self):
            return SubsystemResult("sqlite_store", HealthStatus.HEALTHY)
        def check_memory_manager(self):
            return SubsystemResult("memory_manager", HealthStatus.HEALTHY)
        def check_tool_registry(self):
            return SubsystemResult("tool_registry", HealthStatus.HEALTHY)

    report = _OneDown().check_all()
    assert report["overall"] == "UNHEALTHY"


def test_healthcheck_degraded_propagates():
    from BlackZero.diagnostics.healthcheck import HealthCheck, HealthStatus, SubsystemResult

    class _OneDegraded(HealthCheck):
        def check_model_provider(self):
            return SubsystemResult("model_provider", HealthStatus.DEGRADED, "slow")
        def check_vector_store(self):
            return SubsystemResult("vector_store", HealthStatus.HEALTHY)
        def check_sqlite_store(self):
            return SubsystemResult("sqlite_store", HealthStatus.HEALTHY)
        def check_memory_manager(self):
            return SubsystemResult("memory_manager", HealthStatus.HEALTHY)
        def check_tool_registry(self):
            return SubsystemResult("tool_registry", HealthStatus.HEALTHY)

    report = _OneDegraded().check_all()
    assert report["overall"] == "DEGRADED"


if __name__ == "__main__":
    import sys
    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f"  [PASS] {test.__name__}")
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            failures.append(test.__name__)
    print()
    if failures:
        print(f"FAILED: {len(failures)} tests")
        sys.exit(1)
    else:
        print(f"All {len(tests)} subsystem tests passed.")
        sys.exit(0)
