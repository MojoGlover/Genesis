"""Entry point for ai_starter agent."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

import structlog

from ai_starter.config.settings import load_settings
from ai_starter.core.identity import assert_identity_loaded, load_identity
from ai_starter.core.loop import AgentLoop
from ai_starter.core.state import AgentState, Task, TaskPriority, TaskQueue
from ai_starter.llm.client import OllamaClient
from ai_starter.memory.storage import MemoryStore
from ai_starter.tools.registry import ToolRegistry, register_builtin_tools

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger()


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="AI Starter Agent")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config.yaml",
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--mission",
        type=Path,
        default=Path(__file__).parent / "mission.txt",
        help="Path to mission.txt",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one task and exit (for testing)",
    )
    args = parser.parse_args()

    # Load configuration
    settings = load_settings(args.config)
    data_dir = Path(settings.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    logger.info("starting_agent", config=str(args.config), data_dir=str(data_dir))

    # Load identity
    try:
        identity = load_identity(args.mission)
        assert_identity_loaded(identity)
        logger.info("identity_loaded", name=identity.name, role=identity.role)
    except Exception as e:
        logger.error("identity_load_failed", error=str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        print("Agent cannot start without a valid mission.txt", file=sys.stderr)
        return 1

    # Initialize components
    llm = OllamaClient(settings.ollama)
    memory = MemoryStore(data_dir / "memory.db")
    tools = ToolRegistry()
    register_builtin_tools(tools)

    # Check Ollama availability
    if not await llm.is_available():
        logger.error("ollama_unavailable", base_url=settings.ollama.base_url)
        print(f"ERROR: Ollama not available at {settings.ollama.base_url}", file=sys.stderr)
        print("Start Ollama and try again.", file=sys.stderr)
        return 1

    # Load or create queue
    state_file = data_dir / "state.json"
    if state_file.exists():
        state = AgentState.load(state_file)
        queue = state.queue
        logger.info("state_loaded", tasks=len(queue.tasks))
    else:
        queue = TaskQueue()
        logger.info("new_queue_created")

    # Add a test task if queue is empty (for demo purposes)
    if not queue.tasks:
        logger.info("adding_test_task")
        queue.add(
            Task(
                description="Check system time and write it to /tmp/ai_starter_test.txt",
                priority=TaskPriority.medium,
            )
        )

    # Create agent loop
    loop = AgentLoop(
        identity=identity,
        llm=llm,
        memory=memory,
        tools=tools,
        queue=queue,
        interval_seconds=settings.loop.interval_seconds,
    )

    # Signal handlers for graceful shutdown
    def handle_shutdown(signum, frame):
        logger.info("shutdown_signal_received", signal=signum)
        loop.shutdown()
        queue.save(data_dir / "queue.json")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Run loop
    try:
        if args.once:
            logger.info("running_once_mode")
            result = await loop.tick()
            if result:
                logger.info("once_mode_complete", success=result.reflection.success)
                print(f"\nTask: {result.task.description}")
                print(f"Success: {result.reflection.success}")
                print(f"Summary: {result.reflection.summary}")
                return 0 if result.reflection.success else 1
            else:
                logger.info("once_mode_no_tasks")
                print("No tasks to process.")
                return 0
        else:
            await loop.run()
            return 0

    except Exception as e:
        logger.error("main_loop_error", error=str(e))
        return 1

    finally:
        # Save state on exit
        queue.save(data_dir / "queue.json")
        await llm.close()
        memory.close()


def cli_main():
    """CLI entry point for setup.py."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli_main()
