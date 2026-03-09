"""Tests for the scheduler module."""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from scheduler import Scheduler, Job, JobStatus, IntervalTrigger, DailyTrigger, OnceTrigger


def test_import():
    from scheduler import Scheduler, Job, JobStatus
    assert Scheduler is not None


def test_interval_trigger():
    trigger = IntervalTrigger(minutes=5)
    next_run = trigger.next_run()
    assert next_run is not None


def test_daily_trigger():
    trigger = DailyTrigger(hour=9, minute=30)
    next_run = trigger.next_run()
    assert next_run.hour == 9
    assert next_run.minute == 30


def test_once_trigger_fires_once():
    future = datetime.now() + timedelta(hours=1)
    trigger = OnceTrigger(run_at=future)
    assert trigger.next_run() == future
    assert trigger.next_run(last_run=future) is None


def test_add_job():
    scheduler = Scheduler()
    job = scheduler.add_job(
        func=lambda: "hi",
        trigger=IntervalTrigger(minutes=10),
        name="Test Job"
    )
    assert job.name == "Test Job"
    assert job.id in scheduler.jobs
    assert job.status == JobStatus.PENDING


def test_fluent_api():
    scheduler = Scheduler()
    job = scheduler.every(minutes=5).named("Quick Task").do(lambda: None)
    assert job.name == "Quick Task"


def test_daily_at_fluent():
    scheduler = Scheduler()
    job = scheduler.daily_at(9, 30).named("Morning Task").do(lambda: None)
    assert job.name == "Morning Task"


def test_pause_resume():
    scheduler = Scheduler()
    job = scheduler.add_job(lambda: None, IntervalTrigger(minutes=1))
    scheduler.pause_job(job.id)
    assert not scheduler.jobs[job.id].enabled
    scheduler.resume_job(job.id)
    assert scheduler.jobs[job.id].enabled


def test_remove_job():
    scheduler = Scheduler()
    job = scheduler.add_job(lambda: None, IntervalTrigger(minutes=1))
    scheduler.remove_job(job.id)
    assert job.id not in scheduler.jobs


def test_scheduler_state():
    scheduler = Scheduler()
    scheduler.add_job(lambda: None, IntervalTrigger(minutes=5))
    state = scheduler.get_state()
    assert state.total_jobs == 1
    assert state.pending_jobs == 1
