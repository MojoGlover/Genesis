"""Core scheduler logic."""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional
from pydantic import BaseModel, Field

from scheduler.models import JobStatus, JobResult, JobHistory, SchedulerState
from scheduler.triggers import Trigger


class Job(BaseModel):
    """A scheduled job."""
    
    model_config = {"arbitrary_types_allowed": True}
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    trigger: Trigger
    description: str = ""
    enabled: bool = True
    max_retries: int = 0
    
    # Non-serializable fields
    func: Optional[Any] = Field(default=None, exclude=True)
    args: list = Field(default_factory=list, exclude=True)
    kwargs: dict = Field(default_factory=dict, exclude=True)
    
    # Runtime state
    status: JobStatus = JobStatus.PENDING
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    history: list[JobHistory] = Field(default_factory=list)
    
    def model_post_init(self, __context: Any) -> None:
        """Calculate initial next_run time."""
        self.next_run = self.trigger.next_run()
    
    def is_due(self) -> bool:
        """Check if job is due to run."""
        if not self.enabled or self.status == JobStatus.PAUSED:
            return False
        if self.next_run is None:
            return False
        return datetime.now() >= self.next_run
    
    def update_next_run(self) -> None:
        """Update next run time after execution."""
        self.next_run = self.trigger.next_run(self.last_run)


class Scheduler:
    """Universal job scheduler for AI agents and automations."""
    
    def __init__(self, check_interval: float = 1.0):
        """Initialize scheduler.
        
        Args:
            check_interval: Seconds between job checks
        """
        self.jobs: dict[str, Job] = {}
        self.check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    # --- Job Management ---
    
    def add_job(
        self,
        func: Callable,
        trigger: Trigger,
        name: str = "",
        description: str = "",
        args: list = None,
        kwargs: dict = None,
        enabled: bool = True,
        max_retries: int = 0
    ) -> Job:
        """Add a job to the scheduler.
        
        Args:
            func: Function to call (sync or async)
            trigger: When to run the job
            name: Job name (auto-generated if empty)
            description: Job description
            args: Positional arguments for func
            kwargs: Keyword arguments for func
            enabled: Whether job is active
            max_retries: Number of retries on failure
            
        Returns:
            Created Job
        """
        job = Job(
            name=name or func.__name__,
            trigger=trigger,
            description=description,
            enabled=enabled,
            max_retries=max_retries,
            func=func,
            args=args or [],
            kwargs=kwargs or {}
        )
        self.jobs[job.id] = job
        print(f"✅ Scheduled job: '{job.name}' (ID: {job.id}) | Next run: {job.next_run}")
        return job
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a job.
        
        Args:
            job_id: Job ID to remove
            
        Returns:
            True if removed
        """
        if job_id in self.jobs:
            del self.jobs[job_id]
            return True
        return False
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a job.
        
        Args:
            job_id: Job ID to pause
            
        Returns:
            True if paused
        """
        if job_id in self.jobs:
            self.jobs[job_id].status = JobStatus.PAUSED
            self.jobs[job_id].enabled = False
            return True
        return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job.
        
        Args:
            job_id: Job ID to resume
            
        Returns:
            True if resumed
        """
        if job_id in self.jobs:
            self.jobs[job_id].status = JobStatus.PENDING
            self.jobs[job_id].enabled = True
            return True
        return False
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID.
        
        Args:
            job_id: Job ID
            
        Returns:
            Job or None
        """
        return self.jobs.get(job_id)
    
    def list_jobs(self) -> list[Job]:
        """List all jobs.
        
        Returns:
            List of all jobs
        """
        return list(self.jobs.values())
    
    def get_state(self) -> SchedulerState:
        """Get current scheduler state.
        
        Returns:
            SchedulerState
        """
        jobs = list(self.jobs.values())
        return SchedulerState(
            running=self._running,
            total_jobs=len(jobs),
            pending_jobs=sum(1 for j in jobs if j.status == JobStatus.PENDING),
            running_jobs=sum(1 for j in jobs if j.status == JobStatus.RUNNING),
            completed_jobs=sum(1 for j in jobs if j.status == JobStatus.COMPLETED),
            failed_jobs=sum(1 for j in jobs if j.status == JobStatus.FAILED),
            paused_jobs=sum(1 for j in jobs if j.status == JobStatus.PAUSED),
        )
    
    # --- Execution ---
    
    async def _execute_job(self, job: Job) -> JobResult:
        """Execute a single job.
        
        Args:
            job: Job to execute
            
        Returns:
            JobResult
        """
        job.status = JobStatus.RUNNING
        started_at = datetime.now()
        result = None
        error = None
        
        try:
            if job.func is None:
                raise ValueError("Job has no function assigned")
            
            # Support both sync and async functions
            if asyncio.iscoroutinefunction(job.func):
                result = await job.func(*job.args, **job.kwargs)
            else:
                result = job.func(*job.args, **job.kwargs)
            
            job.status = JobStatus.COMPLETED
            job.run_count += 1
            
        except Exception as e:
            error = str(e)
            job.error_count += 1
            
            # Retry logic
            if job.error_count <= job.max_retries:
                job.status = JobStatus.PENDING
                print(f"⚠️  Job '{job.name}' failed (retry {job.error_count}/{job.max_retries}): {e}")
            else:
                job.status = JobStatus.FAILED
                print(f"❌ Job '{job.name}' failed permanently: {e}")
        
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        # Update job state
        job.last_run = started_at
        job.update_next_run()
        
        # Add to history
        history_entry = JobHistory(
            run_id=str(uuid.uuid4())[:8],
            job_id=job.id,
            started_at=started_at,
            completed_at=completed_at,
            status=job.status,
            error=error,
            duration_seconds=duration
        )
        job.history.append(history_entry)
        
        # Keep only last 50 history entries
        if len(job.history) > 50:
            job.history = job.history[-50:]
        
        # Reset to PENDING for next run if it was COMPLETED and has future runs
        if job.status == JobStatus.COMPLETED and job.next_run:
            job.status = JobStatus.PENDING
        
        return JobResult(
            job_id=job.id,
            status=job.status,
            started_at=started_at,
            completed_at=completed_at,
            result=result,
            error=error,
            duration_seconds=duration
        )
    
    # --- Scheduler Loop ---
    
    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        print("🕐 Scheduler started")
        while self._running:
            due_jobs = [j for j in self.jobs.values() if j.is_due()]
            
            if due_jobs:
                # Run due jobs concurrently
                tasks = [self._execute_job(job) for job in due_jobs]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for job, result in zip(due_jobs, results):
                    if isinstance(result, Exception):
                        print(f"❌ Job '{job.name}' raised: {result}")
                    else:
                        status_emoji = "✅" if result.status in [JobStatus.COMPLETED, JobStatus.PENDING] else "❌"
                        print(f"{status_emoji} Job '{job.name}' | Duration: {result.duration_seconds:.2f}s")
            
            await asyncio.sleep(self.check_interval)
    
    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            print("⚠️  Scheduler already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
    
    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("🛑 Scheduler stopped")
    
    def run_sync(self) -> None:
        """Run scheduler synchronously (blocking). Good for scripts."""
        asyncio.run(self.start())
    
    # --- Convenience Methods ---
    
    def every(self, seconds: int = 0, minutes: int = 0, hours: int = 0) -> 'JobBuilder':
        """Fluent API for adding interval jobs.
        
        Example:
            scheduler.every(minutes=5).do(my_function)
        """
        from scheduler.triggers import IntervalTrigger
        trigger = IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours)
        return JobBuilder(self, trigger)
    
    def daily_at(self, hour: int, minute: int = 0) -> 'JobBuilder':
        """Fluent API for adding daily jobs.
        
        Example:
            scheduler.daily_at(9, 30).do(my_function)
        """
        from scheduler.triggers import DailyTrigger
        trigger = DailyTrigger(hour=hour, minute=minute)
        return JobBuilder(self, trigger)
    
    def cron(self, expression: str) -> 'JobBuilder':
        """Fluent API for adding cron jobs.
        
        Example:
            scheduler.cron("0 9 * * 1-5").do(my_function)
        """
        from scheduler.triggers import CronTrigger
        trigger = CronTrigger(expression=expression)
        return JobBuilder(self, trigger)


class JobBuilder:
    """Fluent builder for creating jobs."""
    
    def __init__(self, scheduler: Scheduler, trigger: Trigger):
        self._scheduler = scheduler
        self._trigger = trigger
        self._name = ""
        self._description = ""
    
    def named(self, name: str) -> 'JobBuilder':
        """Set job name."""
        self._name = name
        return self
    
    def described(self, description: str) -> 'JobBuilder':
        """Set job description."""
        self._description = description
        return self
    
    def do(self, func: Callable, *args, **kwargs) -> Job:
        """Set the function to run and create the job."""
        return self._scheduler.add_job(
            func=func,
            trigger=self._trigger,
            name=self._name,
            description=self._description,
            args=list(args),
            kwargs=kwargs
        )
