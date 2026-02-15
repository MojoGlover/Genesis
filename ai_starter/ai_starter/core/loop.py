"""Autonomous agent loop — plan/execute/reflect cycle."""

import asyncio
import time
from pathlib import Path

import structlog

from ai_starter.core.identity import Identity, get_system_prompt
from ai_starter.core.state import (
    Reflection,
    Step,
    StepResult,
    Task,
    TaskQueue,
    TaskStatus,
    TickResult,
)
from ai_starter.improvement.adaptation import Adapter
from ai_starter.improvement.self_eval import SelfEvaluator
from ai_starter.llm.client import OllamaClient
from ai_starter.llm.prompt_builder import build_plan_prompt, build_reflect_prompt
from ai_starter.llm.response_parser import parse_plan, parse_reflection
from ai_starter.llm.schemas import Message, ToolCall
from ai_starter.memory.retrieval import retrieve_context
from ai_starter.memory.schemas import MemoryCategory, MemoryItem
from ai_starter.memory.storage import MemoryStore
from ai_starter.tools.executor import ToolExecutor
from ai_starter.tools.registry import ToolRegistry

logger = structlog.get_logger()


class AgentLoop:
    """Main autonomous loop: plan → execute → reflect → repeat."""

    def __init__(
        self,
        identity: Identity,
        llm: OllamaClient,
        memory: MemoryStore,
        tools: ToolRegistry,
        queue: TaskQueue,
        interval_seconds: int = 30,
    ):
        self.identity = identity
        self.llm = llm
        self.memory = memory
        self.tools = tools
        self.queue = queue
        self.interval_seconds = interval_seconds
        self.executor = ToolExecutor(tools)
        self.evaluator = SelfEvaluator(llm, memory, identity)
        self.adapter = Adapter(memory)
        self.running = False

    async def run(self) -> None:
        """Main loop: check queue → process task → sleep → repeat."""
        self.running = True
        logger.info("agent_loop_started", identity=self.identity.name)

        while self.running:
            try:
                # Process one tick
                tick_result = await self.tick()

                if tick_result:
                    logger.info(
                        "tick_completed",
                        task_id=tick_result.task.id,
                        success=tick_result.reflection.success,
                        duration_ms=tick_result.duration_ms,
                    )
                else:
                    # No tasks, wait
                    logger.debug("queue_empty", waiting_seconds=self.interval_seconds)

                await asyncio.sleep(self.interval_seconds)

            except Exception as e:
                logger.error("loop_error", error=str(e))
                await asyncio.sleep(self.interval_seconds)

    async def tick(self) -> TickResult | None:
        """Single iteration: plan/execute/reflect for one task."""
        start_time = time.perf_counter()

        # Get next task
        task = self.queue.next()
        if not task:
            return None

        logger.info("processing_task", task_id=task.id, description=task.description)

        try:
            # Plan
            steps = await self.plan(task)
            if not steps:
                self.queue.fail(task, "Planning failed")
                return None

            # Execute
            results = []
            for step in steps:
                result = await self.execute(step)
                results.append(result)
                if not result.success:
                    logger.warning("step_failed", step=step.description, error=result.error)

            # Reflect
            reflection = await self.reflect(task, results)

            # Store results
            self.memory.store(
                MemoryItem(
                    category=MemoryCategory.task_result,
                    content=f"Task: {task.description} | Result: {reflection.summary}",
                    metadata={
                        "task_id": task.id,
                        "success": reflection.success,
                    },
                )
            )

            # Evaluate and store learnings
            eval_report = await self.evaluator.evaluate(
                TickResult(
                    task=task,
                    steps=steps,
                    reflection=reflection,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                )
            )
            self.evaluator.store_learnings(eval_report)

            # Mark complete or failed
            if reflection.success:
                self.queue.complete(task, reflection.summary)
            else:
                self.queue.fail(task, reflection.summary)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return TickResult(
                task=task,
                steps=steps,
                reflection=reflection,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error("tick_error", task_id=task.id, error=str(e))
            self.queue.fail(task, str(e))
            return None

    async def plan(self, task: Task) -> list[Step]:
        """Ask LLM to break task into steps."""
        context = retrieve_context(self.memory, task)
        system_prompt = self.adapter.inject_into_prompt(get_system_prompt(self.identity))

        prompt = build_plan_prompt(task, self.tools.list_tools())

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"{context}\n\n{prompt}"),
        ]

        response = await self.llm.generate(messages)
        steps = parse_plan(response.content)

        logger.info("plan_generated", task_id=task.id, num_steps=len(steps))
        return steps

    async def execute(self, step: Step) -> StepResult:
        """Execute a single step via tool executor."""
        start_time = time.perf_counter()

        try:
            tool_call = ToolCall(tool_name=step.tool_name, arguments=step.tool_args)
            result = self.executor.execute(tool_call)

            logger.info(
                "step_executed",
                tool=step.tool_name,
                success=result.success,
                duration_ms=result.duration_ms,
            )

            return StepResult(
                success=result.success,
                output=result.output,
                error=result.error,
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        except Exception as e:
            return StepResult(
                success=False,
                output="",
                error=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

    async def reflect(self, task: Task, results: list[StepResult]) -> Reflection:
        """Ask LLM to reflect on execution."""
        system_prompt = get_system_prompt(self.identity)
        prompt = build_reflect_prompt(task, results)

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=prompt),
        ]

        response = await self.llm.generate(messages)
        reflection = parse_reflection(response.content)

        logger.info(
            "reflection_complete",
            task_id=task.id,
            success=reflection.success,
            learnings=len(reflection.learnings),
        )

        return reflection

    def shutdown(self) -> None:
        """Graceful shutdown: save state and exit."""
        self.running = False
        logger.info("agent_loop_shutdown")
