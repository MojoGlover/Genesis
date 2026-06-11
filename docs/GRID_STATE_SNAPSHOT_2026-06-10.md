# Grid State Snapshot — 2026-06-10

Freeze-point audit. **Nothing has been stopped, deleted, or modified as a result of this
document.** Purpose: capture exactly what is running, where, and what's inconsistent,
before any consolidation/cleanup decisions are made.

---

## TL;DR

Three separate "PlugOps" instances are running right now, simultaneously, and they
do not agree with each other:

| Instance | Where | Port | State |
|---|---|---|---|
| **plugzero** | Cloud Run (`botico-461107`, us-central1) | 443 (https) | **Primary/canonical per docs.** Healthy, 19 agents registered, 13 online, fresh heartbeats. |
| **plugfoe satellite** | Hetzner VPS 178.105.62.143 | 9000 | Active (`plugops.service`, systemd). 17 agents registered, mostly offline. |
| **plugone satellite** | This Mac ("PlugWan") | 9000 | Active (PID 55009, launchd, since May 22). Not yet queried for agent list. |

Plus a **ghost/misrouted "engineer0" registration** present in *both* plugzero and
plugfoe's registries: `host=100.113.209.66 (plugwan Tailscale IP), port=5003`. Per
cmptrblk/CLAUDE.md, Engineer0 actually lives on **plugfoe at 178.105.62.143:5001**
(confirmed running via `systemctl status engineer0` → active). Nothing is currently
listening on plugone port 5003. This registration is stale/wrong but is showing live
heartbeats in plugzero — meaning either something else answers on that address, or
the heartbeat data itself isn't being live-validated.

---

## Host 1: plugone (Plug1 / "PlugWan" / this Mac)

Agents/services currently running (launchd):

| Service | PID | Port | Notes |
|---|---|---|---|
| Accountant | 6764 | 5002 (no listener observed) | running since May 26 |
| Concierge | 6765 | 5004 | running since May 26 — matches docs |
| CEO | 6848 | **5005** | docs say CEO=5008 — **mismatch** |
| MadJanet | 11082 | **5008** | docs say MadJanet=5003 — **mismatch** (looks swapped with CEO) |
| Goldberg | 19383 | 5006 | matches docs, running since Jun 6 |
| Cerberus (crbrs) | 58991 | 8200 | matches docs; exit code -15 (recently restarted/killed) |
| ComfyUI | 7128 | 8188 | matches docs; plist touched **today (Jun 10)** |
| Atelier | (not currently running — KeepAlive plist, but no live PID found) | 7860 | **New (Jun 9)**, not yet in cmptrblk/CLAUDE.md. `art/atelier/server.py` — "Goldberg's dedicated art UI." Log shows it started ("Atelier v2 on http://localhost:7860") at some point but no process found at audit time. |
| Local PlugOps satellite | 55009 | **9000** | running since **May 22** — duplicate of plugfoe's satellite on the same port |
| 12 infra modules (registry, ledger, mind_state, policy_gate, model_gateway, communication, supervisor, tool_bus, observability, secrets, file_store, event_bus) | 51452–51461 | 9100–9109 | All marked "⏳ planned / 🔬 in validation" in cmptrblk/CLAUDE.md, but **all are actually live** here |
| plugwan-watcher | 46247 | — | launchd watcher |

Not currently loaded/running locally: `com.cmptrblk.engineer0` (good — consistent with
Engineer0 having moved to plugfoe). `engineerx` and `engineerv` plists exist but are
unloaded (PID `-`, exit 0).

---

## Host 2: plugfoe (Hetzner VPS, 178.105.62.143)

systemd services, all `active (running)`:
- `engineer0.service` — Engineer0 Agent (canonical home per CLAUDE.md, port 5001)
- `plugops.service` — "PlugOps Agent Grid Router" (satellite, port 9000)
- `watchdog-plugops.service` — "Computer Black PlugOps + Satellites Watchdog"

Local registry (`:9000/api/v1/agents`) — 17 agents:

| Agent | Status | Host | Port |
|---|---|---|---|
| engineer0 | **online** | 100.113.209.66 (plugwan tailscale) | 5003 ⚠️ ghost, see TL;DR |
| madjanet | offline | — | 5003 |
| cerberus | offline | — | 8200 |
| accountant | offline | — | 5002 |
| ceo | offline | — | 5005 |
| concierge | offline | — | 5004 |
| math | offline | — | 5007 |
| editor_in_chief | offline | — | 5015 |
| writer | **online** | — | — |
| editor | offline | — | 5017 |
| seo_analyst | **online** | — | — |
| analytics_agent | offline | — | 5019 |
| publisher | **online** | — | — |
| social_distributor | **online** | — | — |
| goldberg | offline | — | 5006 |
| researcher | **online** | — | — |
| sol | **online** | — | — |

---

## Host 3: plugzero (Cloud Run — `botico-461107`, us-central1)

- URL: `https://plugzero-fmhdkkt4oq-uc.a.run.app` (alias `plugzero-581737577470.us-central1.run.app`)
- Latest ready revision: `plugzero-00030-mfk`, deployed **2026-05-31**
- `/health`: `{"status":"healthy","agents_total":19,"agents_online":13,"plugins_loaded":0,"ws_connections":0,"profiles_running":0,"heartbeat_alive":true}`

19 registered agents, 13 online with fresh (~seconds-old) heartbeats:
`engineer0*, madjanet, cerberus, accountant, ceo, concierge, researcher, writer,
seo_analyst, publisher, social_distributor, sol, goldberg`

6 offline: `math (5007), editor_in_chief (5015), editor (5017), analytics_agent (5019),
luna (5012), process_manager (8300)`

\* engineer0 entry has the same `100.113.209.66:5003` ghost address as on plugfoe.

**Known bug:** `/docs` and `/openapi.json` crash repeatedly (every ~20–30 min) with a
`pydantic`/`fastapi` schema-generation `TypeError` (`get_definitions` /
`generate_definitions` — version incompatibility). Core routing/heartbeats appear
unaffected, but the OpenAPI surface is broken on revision 00030.

---

## Open questions / decisions needed before any stop/delete action

1. **Which PlugOps instance is "the" instance going forward?** Right now plugzero is
   the only one with most agents online and live heartbeats — it's the de facto
   primary. plugfoe's and plugone's local `:9000` satellites both exist but mostly
   show offline agents.
2. **What is actually answering as `engineer0` at `100.113.209.66:5003`?** That
   address/port doesn't match anything we found running on plugone, and isn't
   plugfoe's real Engineer0 (178.105.62.143:5001). Needs to be traced before deciding
   whether to fix the registration or whether something stale is still alive there.
3. **CEO/MadJanet port swap on plugone** (5005/5008 vs documented 5008/5003) —
   likely contributing to routing confusion.
4. **"Atelier"** (port 7860, Goldberg's art UI, added Jun 9) and **ComfyUI plist
   touched today** — both undocumented in cmptrblk/CLAUDE.md. Need a one-line entry
   each per the "document non-standard decisions inline" rule.
5. **plugzero OpenAPI crash** — separate bug, low urgency, but worth a ticket.

No services were stopped, no Cloud Run revisions deleted, no registries modified
during this audit.

---

## UPDATE (same session, later 2026-06-10): Engineer0 audit fix + full grid shutdown

After the audit above, the following actions were taken at Darnie's explicit,
repeated instruction ("stop the bleeding," full reset before redeployment).

### 1. Engineer0 ghost-registration — root cause found and fixed

`~/Engineer0/config.yaml` on plugfoe (`plugops_bridge` section) hardcoded
`host: "100.113.209.66"` (plugwan's Tailscale IP) — a leftover from before
Engineer0 moved to plugfoe on 2026-06-05. The 2026-06-05 fix only corrected
`agents.yaml` on the PlugOps side; Engineer0's own self-reported registration
address was never updated. Result: `GET /api/v1/agents/engineer0/url` resolved to
a dead address (`http://100.113.209.66:5003`), so any agent/tool-bus call routed
through that lookup would have silently failed.

**Fixed:** `host` → `178.105.62.143` (plugfoe), restarted `engineer0.service`,
confirmed plugzero registry updated to `api_url: http://178.105.62.143:5003` with
live heartbeats. Stale comments in config.yaml updated to match. Logged in
cmptrblk/CLAUDE.md Undocumented Changes Log (2026-06-10 entries).

**Also flagged, not yet fixed:** `PLUGOPS_AGENT_URL_ENGINEER0` (Cloud Run env var,
set 2026-06-05) still points at port `5001`. Engineer0's actual API port is `5003`
(confirmed via `/health`). Needs reconciling on next deploy.

`engineerx` / `engineerv` (Eng_Team variants under `Engineer0/Eng_Team/`) are
**separate agents, not duplicate Engineer0 instances** — they were unloaded/not
running on this Mac, and only `engineer0` itself was running on plugfoe (single
instance, no noncanonical copies found).

### 2. Supervisor module — fully removed

- Stopped, unloaded `com.cmptrblk.mod.supervisor` (was nonfunctional, port 9103)
- Deleted `Botico/modules/supervisor/v1/` (sealed copy)
- Deleted `GENESIS/modules/supervisor/` (source/validation copy)
- Port 9103 confirmed free

### 3. Full grid shutdown — everything stopped, nothing deleted (except supervisor above)

**This Mac (plugone / PlugWan) — all stopped:**
- Agents: Accountant, Concierge, CEO, MadJanet, Goldberg, Cerberus (crbrs)
- `engineerx`, `engineerv` (Eng_Team variants)
- Atelier (Goldberg's art UI v2, port 7860 — new as of 2026-06-09, not yet in
  cmptrblk/CLAUDE.md)
- ComfyUI (port 8188)
- All 12 infra modules (registry, ledger, mind_state, policy_gate, model_gateway,
  communication, tool_bus, observability, secrets, file_store, event_bus —
  supervisor already removed). **New finding:** these were all live despite
  cmptrblk/CLAUDE.md marking them "⏳ planned" / "🔬 in validation."
- `plugwan-watcher`
- The local PlugOps satellite on port 9000 (PID 55009, `python -m plugops.api.server`,
  running since May 22). **New finding:** this process was *not* managed by any
  launchd plist — it was a manually-started orphan, killed directly.

**All 23 `com.cmptrblk.*.plist` files moved (not deleted) to:**
`~/Library/LaunchAgents/disabled_cmptrblk_2026-06-10/`
→ Nothing will reload at next login/reboot. To bring something back, move its
plist back to `~/Library/LaunchAgents/` and `launchctl bootstrap gui/$(id -u) <plist>`.

**plugfoe (178.105.62.143) — all stopped AND disabled (won't survive reboot):**
- `engineer0.service` — stopped, disabled
- `plugops.service` (local satellite, port 9000) — stopped, disabled
- `watchdog-plugops.service` — stopped, disabled. **New finding:** this had
  `Restart=always` and was the thing that would have silently restarted
  Engineer0/the satellite if just stopped without disabling — it's been running
  since 2026-06-05 and monitors "PlugOps + Satellites."
→ To re-enable: `systemctl enable --now <service>` for each, on plugfoe.

### 4. plugzero (Cloud Run) — DELETED

Per Darnie's explicit instruction ("when I said delete, I meant plugzero" +
"not a single kilobyte of data working"), the Cloud Run service `plugzero`
(`botico-461107`, us-central1, revision `plugzero-00030-mfk`) was deleted.
Verified: `gcloud run services list` returns 0 items; the service URL now
returns HTTP 404.

Nothing irreplaceable was lost: `agents.yaml` and `plugops/config/agent_profiles.json`
live in the MojoGlover/PlugOps git repo (source of truth, redeployable). The
"13 online" agents shown in the TL;DR table above were stale heartbeat display
(`ws_connections: 0`, `profiles_running: 0` even before deletion) — no live
continuity snapshots were running on the container's ephemeral filesystem.

### Net result

**Everything is now stopped: this Mac, plugfoe, and Cloud Run.** Nothing in the
grid is running anywhere. All configs/code preserved (moved, not deleted, except
the confirmed-nonfunctional supervisor module). To redeploy plugzero from scratch:
`gcloud run deploy` from the PlugOps repo using the existing Dockerfile/config.
