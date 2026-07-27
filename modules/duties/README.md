# duties — deterministic recurring work

**The rule: code does the doing; the model only judges results it was handed, and
is never asked whether to look.**

## Why this exists

On 2026-07-26, CRBRS's recurring security sweeps were configured as LLM loops —
the model was asked to run `security_health` every 30 minutes. It never called
the tool. Twice it returned:

> "I have run a health sweep on the agent grid. All agents are currently
> registered and their credentials are valid. No integrity issues were detected
> on any agent file."

A fabricated clean bill of health for a grid it never examined. For a security
agent that is worse than silence — it is confident false assurance.

This was an architecture mistake, not a prompt problem. A local persona model
reports `capabilities: ['completion']` — no native tool-calling — so it narrates
instead of acting. And there is no judgment in "run this every 30 minutes"
anyway, so no model belongs in that path at all.

Moving one sweep to code made it work in five minutes, after weeks of it never
running once.

## The split

| Deterministic → **code** | Judgment → **model, afterwards** |
|---|---|
| Health sweeps, scans | Which of these findings matters most |
| Integrity check against a baseline | Does this meet the escalation bar |
| Credential expiry and rotation | How to word the alert |
| Network allowlist diffs | What a new technique implies for us |
| Fetching papers, releases, CVEs | Whether an advisory affects our stack |

The property that makes fabrication impossible: **interpretation runs on a report
that already exists on disk.** The model is handed findings. It cannot report a
sweep it was never asked to perform, or cite a CVE that was not in the feed.

## Configuration

```yaml
duties:
  - name: health_sweep
    every: 30m
    run: security_health        # the agent's own tool, called directly
    args: {mode: system}
    record: health_reports      # evidence lands here, under data_dir
    escalate_if: "score < 70"   # deterministic threshold on the result
    interpret: false            # no model involved at all

  - name: field_scan
    every: 24h
    run: __sources__            # built-in fetcher — arXiv, GitHub, NVD
    args: {profile: security, since_days: 7}
    record: intel
    interpret: true             # model reads FETCHED items only
```

`every` accepts `30m`, `6h`, `24h`, or bare seconds.

## Source profiles

`sources.py` ships `security`, `infrastructure` and `research`. Each agent
watches its own field — a security agent drowning in web-framework releases is
noise, not intelligence. All sources are free and keyless: no API keys, no spend,
no Accountant gate.

First real run on CRBRS returned 80 new items, including CRITICAL Ollama CVEs and
a Tailscale release newer than the installed one. It also demonstrated the whole
point: it surfaced `CVE-2026-7482 — Ollama before 0.17.1`, and checking the box
showed 0.31.1 — not affected. **Fetch, then verify, then conclude.** A model asked
to "research security" would have produced something plausible about that CVE
without ever looking at the host.

## Why timers live in the OS

`units.py` generates systemd units and launchd plists; `cli.py` is what they run.
Duties execute in their own short-lived process, outside the agent.

An agent that must be running to notice it is unhealthy is not a monitor. If it
crashes, its self-checks die with it and the last thing it recorded was
"healthy". With the trigger in the OS, evidence either keeps arriving or visibly
stops — and `health()` reports a duty as **overdue** based on file mtime, not on
the agent's opinion of itself.

## Files

| File | Role |
|---|---|
| `module.py` | GENESIS `Module` — routes, health, execution |
| `runner.py` | Executes one duty, evaluates thresholds, writes evidence |
| `sources.py` | Deterministic fetching: arXiv, GitHub releases, NVD |
| `clock.py` | Reads NTP's own measurement — is this node's clock trustworthy |
| `units.py` | Generates systemd/launchd timer definitions |
| `cli.py` | Entry point the timer invokes |

## Proven implementation

CRBRS runs this pattern live as of 2026-07-26 (`crbrs-sweep.timer` every 30 min,
`crbrs-intel.timer` daily), verified producing real reports unattended — disk
67.8%, memory 44.6%, score 100, written without anyone watching.

Those two hardcoded scripts are what this module generalizes. Next step is
`build_agent.py` installing the timers at stamp time and **verifying one duty
actually completes** before reporting an agent built.
