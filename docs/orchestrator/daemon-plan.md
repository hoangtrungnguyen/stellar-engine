# `se orchestrator run` — daemon plan

## Status

🟨 **D0 scaffolded** (2026-05-21). `agents/orchestrator/cli/daemon.py`
exists as a stub; `se orchestrator run` is wired through but every
invocation prints a one-line message and exits 0. Phases D1–D6 still
to do.

The one-shot CLI wrappers shipped today (`se orchestrator deploy`,
`route`, `pick`, `fix-bug *`, `qa *`, `expand`, `doctor`) are stateless
single-fire calls — an operator (or cron job) drives them manually.

The daemon replaces "operator-as-loop" with a long-running process that
polls the grava backlog, dispatches ready issues to teams, and respects
concurrency limits.

## Context

Today's flow:

```
operator → `se orchestrator deploy` → route + Phase 0 → manual phases
        ↑ (next issue, hours later)
```

Target flow:

```
daemon (one per fleet instance)
  ├─ poll repos.yaml every N seconds
  ├─ for each repo: pick_ready(team) → route → dispatch Phase 0
  ├─ track in-flight pipelines (max_concurrent per repo, global cap)
  ├─ heartbeat watcher: surface stalled wisps
  └─ pause/resume on failure streaks
```

Operator's role narrows to:
- Configuring `repos.yaml` + `policies/`.
- Driving Phase 1 (the human-in-loop steps: bug fix, QA review) inside Claude Code.
- Reviewing fleet status (`se orchestrator status`).

## Non-goals (for this phase)

- Distributed coordination — single daemon process per host.
- Web UI — `se orchestrator status` CLI is enough.
- Cross-repo dependency awareness — each repo runs independently.

> ~~Replacing `pr_merge_watcher.sh` cron — it's already in place, keep
> it.~~ **Superseded (2026-05-21):** Phase D6 below absorbs the bash
> watcher into the daemon as a separate 300s tick. The bash script will
> be deleted in D6.

## Scope

```
se orchestrator run        [--repos repos.yaml] [--policies policies/]
                           [--once] [--max-concurrent N]
                           [--log-level INFO]
se orchestrator status     [--json]                     # in-flight + recent
se orchestrator pause      <repo>                       # write a pause flag
se orchestrator resume     <repo>
```

`--once` runs a single tick (poll + dispatch) and exits. Useful for cron
mode and CI.

## Phases

### Phase D0 — scaffolding (no behaviour change)

- New script `agents/orchestrator/cli/daemon.py` with a stub `main(argv)`
  that just prints "daemon: not implemented" and exits 0. Lets us wire
  `cmd_orchestrator_run` in `cli/se` and ship the subcommand surface
  without behaviour.
- Add `se orchestrator run --once` flag plumbing (no-op for now).
- Smoke test: `python3 cli/se orchestrator run --once --help`.

### Phase D1 — tick loop

- Replace stub with real loop:
  1. Load `repos.yaml` (existing `_load_repos` in `cli/se`).
  2. For each `repo` (parallel via `concurrent.futures.ThreadPoolExecutor`):
     a. Read `<repo>/.grava/orchestrator-paused` — skip if present.
     b. For each team (`fix-bug`, `epic-task`, `qa`, `task-generator`):
        - Read in-flight count from `grava wisp` index (count of
          `pipeline_phase` values not in `{"", "complete", "failed"}`).
        - If `inflight >= repo.max_concurrent`, skip team.
        - Else: invoke `pick_ready --team T --limit 1`. If non-empty:
          dispatch Phase 0 (`fix_bug_claim` / `qa_load` / `task_gen_expand`).
  3. Sleep `repo.poll_interval` (default 60s) — unless `--once`.
- Write a global wisp `daemon_last_tick=<unix>` to a status file at
  `~/.local/share/stellar-engine/daemon.json` (atomic write).
- Honour SIGINT/SIGTERM for graceful shutdown (drain in-flight dispatches).

### Phase D2 — heartbeat watcher

- Each tick, also scan in-flight pipelines for stale heartbeats:
  - Read `policies/default.yaml#heartbeat.stale_threshold_minutes`
    (default 10).
  - For each in-flight wisp, compare `orchestrator_heartbeat` to now.
  - If stale: label the issue `stale-pipeline`, write a comment with
    the last phase, and surface in `se orchestrator status`.
- No auto-recovery — operator decides.

### Phase D6 — pr-lifecycle ticker (absorbs `pr_merge_watcher.sh`)

> Sequencing note: numbered D6 to keep the existing D3/D4/D5 IDs stable.
> In implementation order, D6 lands after D1 (it depends on the scheduler)
> and before D5 (the systemd unit should advertise both tickers).

- Add a second ticker alongside the backlog ticker built in D1.
  Two cadences in one process, one scheduler:
  - **backlog ticker**: 60s (D1) — pick_ready → Phase 0 dispatch
  - **pr-lifecycle ticker**: 300s (D6) — PR state diff → signals/labels
- New module `agents/orchestrator/runtime/pr_state.py` — pure
  `next_state(snapshot, view, now, policy) -> (state, events)`.
  Zero I/O, unit-testable. Replaces the nested-switch logic in
  `pr_merge_watcher.sh`.
- New adapters `runtime/adapters/grava.py`, `runtime/adapters/github.py`
  — thin subprocess wrappers. GitHub adapter uses `gh api graphql` for
  bulk PR fetch (one call per repo per tick, not N+1).
- New composition `runtime/pr_watcher.py` — `PRWatcher.tick(repo_path)`.
  Singleton via `fcntl.flock` on `.grava/pr-watcher.lock` (replaces
  pidfile in the bash script — no PID-recycle bugs).
- Wisp schema centralizes on `pr_state` (enum) + `pr_state_changed_at`.
  First tick migrates from the scattered booleans (`pr_stale`,
  `pr_rejection_recorded`, `pr_merged_at`, `pr_rejection_reason`) that
  the bash watcher wrote.
- Per-team re-entry hints move from `case "$TEAM"` to a `TEAM_HANDLERS`
  dict (`fix-bug → /deploy <id> --retry`, `epic-task → /ship <id>
  --retry`, etc.). Adding a team = one dict entry.
- **Delete** `agents/orchestrator/scripts/pr_merge_watcher.sh` and
  the `_check_cron` row in `cli/se`'s doctor checks.

Configuration (new section in `policies/default.yaml`):
```yaml
pr_watcher:
  enabled: true
  interval_seconds: 300
  stale_threshold_hours: 72
  github_api:
    batch_max: 50
    timeout_seconds: 30
    backoff: { base_seconds: 5, max_seconds: 300 }
  on_terminal_state: "remove_label"   # un-label `pr-created` once MERGED/CLOSED
```

See [[pr-watcher-redesign]] in memory for the full design rationale,
the three-layer architecture (pure / adapters / composition), and the
old → new wisp-schema mapping.

### Phase D3 — failure streak pause

- Track per-repo failure count in
  `~/.local/share/stellar-engine/state/<repo>.json`:
  ```json
  { "failure_streak": 2, "last_failure": "2026-05-18T10:00:00Z" }
  ```
- Increment on Phase 0 dispatch errors (route exit != 0, claim failure,
  etc.). Reset on successful dispatch.
- When streak ≥ `policies.pause_on_failure_streak` (default 3): touch
  `.grava/orchestrator-paused` in the repo, write a comment to the
  most-recent failed issue. Daemon skips this repo until operator runs
  `se orchestrator resume <repo>`.

### Phase D4 — status command

```
se orchestrator status [--json] [--repo R]
```

Renders:
- Daemon uptime (`daemon_last_tick`).
- Per-repo: in-flight count, last tick, paused?, failure streak.
- Per-team in-flight pipelines (`<repo>: <id> <team> <phase> <heartbeat>`).
- Stale pipelines (label `stale-pipeline`).

Reads from grava wisps + daemon state file. Does not mutate.

### Phase D5 — systemd / launchd unit

- Ship `scripts/systemd/stellar-orchestrator.service` (Linux) +
  `scripts/launchd/com.stellar.orchestrator.plist` (macOS) so operators
  can install via `bash scripts/install.sh --enable-daemon`.
- `se orchestrator install-daemon` writes the unit file + activates it.

## Critical files (when built)

**New**:
- `agents/orchestrator/cli/daemon.py` — tick loop, signal handling.
  ✅ D0 scaffold landed (stub `main(argv)` only; flags plumbed forward).
- `agents/orchestrator/cli/status.py` — read-only status renderer.
- `agents/orchestrator/runtime.py` — shared helpers (in-flight counting,
  state-file I/O, policy loading).
- `agents/orchestrator/runtime/pr_state.py`,
  `runtime/pr_watcher.py`, `runtime/adapters/{grava,github}.py`
  — D6 PR-watcher rewrite (replaces `scripts/pr_merge_watcher.sh`).
- `scripts/systemd/stellar-orchestrator.service`,
  `scripts/launchd/com.stellar.orchestrator.plist`.
- `docs/orchestrator/daemon-ops.md` — operator runbook (start, stop,
  pause, drain, debug).

**Modify**:
- `cli/se` — add `cmd_orchestrator_run` ✅ D0, plus
  `cmd_orchestrator_status`, `cmd_orchestrator_pause`,
  `cmd_orchestrator_resume` (later phases).
- `agents/orchestrator/AGENT.md` — add "Daemon mode" section after
  "Entry commands".
- `CLAUDE.md` — remove the "fleet runtime is unbuilt" caveat once D1
  lands. Add `se orchestrator run` to the operator entry points.
- `scripts/install.sh` — `--enable-daemon` flag.

**Delete (in D6)**:
- `agents/orchestrator/scripts/pr_merge_watcher.sh` and the
  `_check_cron` row in `cli/se`'s doctor checks.

## Verification

For each phase:

- **D0**: `python3 cli/se orchestrator run --once` prints stub message, exit 0.
- **D1**: Wire two grava repos in `repos.yaml`, plant one ready bug
  + one ready epic each, run `--once`. Verify 4 Phase 0 dispatches
  fire and `pipeline_phase` advances. Re-run `--once`: zero new
  dispatches (idempotent).
- **D2**: Plant a wisp with `orchestrator_heartbeat=<2 hours ago>`. Run
  `--once`. Verify `stale-pipeline` label applied + comment posted.
- **D3**: Force 3 consecutive dispatch failures. Verify `.grava/orchestrator-paused`
  file appears. `resume` removes it.
- **D4**: `se orchestrator status` shows both repos, in-flight pipelines,
  stale entries.
- **D5**: `systemctl status stellar-orchestrator` (Linux) /
  `launchctl list | grep stellar` (macOS) reports active. Killing process
  triggers auto-restart.
- **D6**: Plant a `pr-created` label + `pr_number` wisp on a merged PR.
  Run `--once`. Verify: `pr_state` wisp = `merged`, issue closed, label
  `pr-created` removed, single `PR_MERGED` + `PIPELINE_COMPLETE` signal
  pair emitted (not duplicated across ticks). Bash watcher binary
  removed; doctor no longer reports the cron row.

## Risks

- **In-flight counting via wisps**: `grava wisp` index isn't optimised
  for fleet-wide queries. May need a grava-side index or a per-issue
  scan. Bench D1 against a 100-issue repo before locking in.
- **Phase 0 dispatch is fast (~seconds)**, but `fix_bug_claim` provisions
  a worktree — disk-bound. Single-threaded per repo is fine; cross-repo
  parallelism via thread pool.
- **Daemon ≠ source of truth**: grava wisps remain the state machine.
  Daemon is a poller + dispatcher only. If the daemon crashes, the
  pipeline state is intact; another daemon (or operator) can resume.
- **Policy hot-reload**: don't bother for now. Daemon restart picks up
  config changes.
- **Failure streak false positives**: a single grava issue with bad
  metadata can poison the streak counter. Mitigation: only count
  "dispatch error" failures, not user-driven errors (verify exit 5,
  qa report fail).

## Out of scope

- Distributed daemon (k8s, etc.). Single-host only.
- Cross-repo dependency ordering (issue X in repo A blocks issue Y in
  repo B). Each repo runs independently.
- Web dashboard. CLI status only.
- Auto-merge of PRs after green checks — `pr_merge_watcher.sh` handles
  external merges only.
- Replacing the `/ship` slash command (epic-task team continues to need
  Claude Code; daemon dispatches to a "needs operator" queue).

## When to start

Block D0 until:
1. The wrappers shipped in this PR (route/pick/deploy/expand/fix-bug/qa)
   have ≥ 1 week of operator use with no regressions.
2. `se orchestrator deploy` has run end-to-end against at least 5
   real issues across 2 repos.
3. The wisp-based in-flight counting query is benchmarked at ≤ 200 ms
   on a 100-issue grava repo.

Once those three gates pass, D0 is a small (under 100 lines) scaffold PR.
