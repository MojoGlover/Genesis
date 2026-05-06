"""Communication module node — minimal message-passing hub.

HTTP endpoints:
  POST /register      {agent_id}
  POST /send          {from, to, payload}
  GET  /inbox/{id}    SSE stream of messages for that agent
  GET  /health
  GET  /stats
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse
import uvicorn

DB_PATH = Path(__file__).parent / "node.db"

app = FastAPI(title="Communication Node")

inboxes: dict[str, asyncio.Queue[dict]] = {}
stats = {"registered": 0, "sent": 0, "delivered": 0, "dropped_unknown_recipient": 0}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                registered_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )


class RegisterBody(BaseModel):
    agent_id: str


class SendBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    payload: dict


@app.on_event("startup")
async def _startup() -> None:
    init_db()


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "ts": time.time()}


@app.get("/stats")
async def get_stats() -> dict:
    return {**stats, "inboxes": {k: v.qsize() for k, v in inboxes.items()}}


@app.post("/register")
async def register(body: RegisterBody) -> dict:
    aid = body.agent_id
    if aid not in inboxes:
        inboxes[aid] = asyncio.Queue()
        stats["registered"] += 1
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agents(agent_id, registered_at) VALUES (?, ?)",
            (aid, time.time()),
        )
    return {"ok": True, "agent_id": aid}


@app.post("/send")
async def send(body: SendBody) -> dict:
    stats["sent"] += 1
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(ts, from_agent, to_agent, payload) VALUES (?, ?, ?, ?)",
            (time.time(), body.from_, body.to, json.dumps(body.payload)),
        )
    q = inboxes.get(body.to)
    if q is None:
        stats["dropped_unknown_recipient"] += 1
        raise HTTPException(status_code=404, detail=f"unknown recipient: {body.to}")
    await q.put({"from": body.from_, "payload": body.payload, "ts": time.time()})
    stats["delivered"] += 1
    return {"ok": True}


@app.get("/inbox/{agent_id}")
async def inbox(agent_id: str):
    if agent_id not in inboxes:
        inboxes[agent_id] = asyncio.Queue()

    async def event_stream():
        q = inboxes[agent_id]
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield {"event": "message", "data": json.dumps(msg)}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(event_stream())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100, log_level="info")
