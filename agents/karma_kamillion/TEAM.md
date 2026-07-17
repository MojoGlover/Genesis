# Karma KaMillion — Team Spec

> Status: **Proving Ground** (Genesis stage). Members run standalone,
> no Coordinator, no PlugOps wiring. This file is the team's source of
> truth; the reusable pattern it follows lives in
> `GENESIS/docs/TEAM_TEMPLATE.md`.

## Mission

Mine public platforms for high-engagement story material — complaints,
conflicts, tell-alls, viral grievances — and surface a ranked shortlist
of candidates. Each member covers one platform and one signal type;
the team's output is "here are today's N most promising raw stories,
with evidence for why."

*(End consumer of the shortlist — content pipeline, "What Had Happened
Was" network, or something else — not yet confirmed by Darnie. The
crawlers are consumer-agnostic on purpose: they emit ranked JSON,
nothing downstream-specific.)*

## Roster

### Built + tested (2026-07-17)

| Member | Platform | Signal | Cost |
|---|---|---|---|
| `reddit_crawler` | Reddit (public new.json, no OAuth) | comment velocity + upvote ratio + cross-title phrase clustering | free tier, self-gated 100 req/min |
| `youtube_crawler` | YouTube Data API v3 | reply depth + negative-sentiment intensity on comment threads | 10k units/day, self-gated with persisted state |

Both: CLI + `--dry-run`, config-driven watchlists, Chronicle-compatible
structured logging (not POSTed anywhere yet), scoring cores covered by
tests.

**These are deterministic Python daemons, not BlackZero agents.** No LLM,
no mission.txt, no PlugOps bridge. That's deliberate — see the template
doc's "daemon vs. agent" rule. They only get stamped into agent-hood if a
step ever genuinely needs judgment.

### Planned (proposals — need Darnie's go, not started)

- **`curator`** — merges both crawlers' ranked lists, dedupes the same
  story appearing on multiple platforms, applies any human blocklist,
  emits the single unified team shortlist. First candidate for a real
  (LLM) agent, since "is this actually a good story?" is judgment.
- **`coordinator`** — team lead: schedules crawls, forwards
  Chronicle-formatted logs to real Chronicle ingest, exposes the
  shortlist to the grid. This is the Proving Ground exit — building it
  IS the graduation step.
- More platform crawlers only when the first two prove out.

## External accounts

Service email: `kkamillion.botico@gmail.com` (logged in Cerberus's
`key_registry.md` External Accounts section). Telegram bot
`karmak_botico_bot` — token in team-root `.env` (gitignored; purpose of
the bot not yet wired to anything).

## Open items

1. YouTube watchlist still has the placeholder channel ID
   (`UC_x5XG1OV2P6uZZ5FSM9Ttw` is Google's own developer channel) —
   needs Darnie's real target channels.
2. YouTube crawler needs `YOUTUBE_API_KEY` in its `.env` (see
   `.env.example`) before a non-dry run.
3. No cron/launchd schedule yet — both run manually. Scheduling is fine
   pre-graduation; wiring to Coordinator is not.
4. Downstream consumer unconfirmed (see Mission).

## Graduation criteria (Proving Ground → Purgatory → Botico)

Per `Botico/BOTICO_CANON.md` lifecycle. Concretely for this team:

- [ ] Both crawlers have run on a real schedule for a sustained stretch
      without quota violations or crashes (evidence: their own logs)
- [ ] Real watchlist + API key in place; output judged actually useful
      by Darnie at least once
- [ ] Coordinator built; Chronicle ingest wired; KNOWN_AGENTS entry added
      in cerberus_policy.py (onboarding requirement)
- [ ] Ports assigned by build_agent.py — never hand-picked
