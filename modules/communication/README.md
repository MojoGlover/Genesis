# Communication Module

Minimal message-passing hub for GENESIS agents. HTTP + Server-Sent Events. No WebSockets.

## Pieces

- `node/server.py` — FastAPI hub on port 9100. SQLite-backed registry + message log.
- `client.py` — reusable `CommClient` (register, send, SSE inbox with auto-reconnect).
- `tests/` — unit tests.

## Node endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/register` | `{agent_id}` — register to receive messages |
| POST | `/send` | `{from, to, payload}` — send to another registered agent |
| GET | `/inbox/{id}` | SSE stream of messages for that agent |
| GET | `/health` | liveness |
| GET | `/stats` | counters + inbox depths |

## Validation

Stress harness lives at `GENESIS/evals/communication_stress/`. Module is not
considered validated until that harness completes a long run with zero errors.

Per GENESIS Rule 21 (Proving Ground), this module does **not** move to Botico
until validation passes.
