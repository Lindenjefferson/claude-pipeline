#!/usr/bin/env python3
"""Delivery ledger: one JSON line per agent run, grouped in cycles, so the manager sees what is pending.

  start   --slug <slug> [--base <rev>] [--plan <path>] [--archive]       once per delivery
  add     --agent dev --task <id> --verdict <v> [--simpler] [--seconds <duration>] [--tokens N]
  add     --agent reviewer|qa --verdict PASS|FAIL [--critical N --important N --minor N --origin <origin>=N,...]
          [--report <path>] [--seconds <duration>] [--tokens N]
  add     --agent reviewer --task spec|plan|security --verdict PASS|FAIL ... [--triage applied=N,refused=N,errata=N]
                                                              one round of the spec, plan or security review loop
  add     --agent qa ... --full | --interface                 the qa ran the full test command, or the interface
  claim   --task <id> [--worktree <path>] [--origin <rev>]    a dev run dispatched; refused if the task is in flight or done
  release --task <id>                                         frees a claim whose run was lost
  pause   --text <text>                                       the delivery stops; the text says what comes on return
  resume                                                      the work restarts; lists the claims still in flight
  measure --agent dev|reviewer|qa [--task <id>] [--at <at>] [--seconds <duration>] [--tokens N]  numbers of a run added
  note    --text <text> [--validar --recommend <text>]        a decision taken on the user's behalf
  validate --id <id> --decision <text>                        the user's decision on a VALIDAR item (V1, V2...)
  waive   --agent reviewer|qa [--task spec|plan] --reason <text>   accepts the open findings of that agent's latest FAIL
  extend  --reason <text> [--task spec|plan]                  the user lets the fixes, or that review loop, go on
  plan    --path <path>                                       the approved plan, when start ran before it existed
  scope   --cycle <name> --tasks <id,id,...>                  the tasks of one plan cycle, in plan order
  mode    autonomous [--until <HH:MM or ISO time>]|supervised  the user turned autonomous mode on, or is back
  defer   --text <text> --recommend <text>                    an item left for later; prints its id (D1, D2...)
  resolve --id <id> --decision <text>                         the final decision on a deferred item
  lesson  --text <rule> [--check <test or lint rule>]         a lesson, automated when --check names the check
  status  [--json] [--check]                                  the current cycle, what it still needs, and metrics
  capacity [--json]                                           free memory and disk, and the parallel copies that fit

A claim is written when the dev is dispatched and freed by the dev's add (or release); status lists the tasks in
flight and the gate waits for them, so a manager resuming after a compaction sees which runs it still owes a report.
claim refuses a task that is in flight or already DONE in the current cycle, so one task never runs twice by mistake.
--worktree (an existing directory) and --origin (a commit, resolved to its hash there) are kept with the claim; status
shows them and, when the delivery head is no longer the origin, names the head (a fact: it moves with every
integration). A claim's tip is its worktree's current HEAD (null with no worktree or folder): resume prints
"- <task> in <worktree> at <tip>", the commit the dev's brief names, since a wip commit moves the work past the origin.
pause is refused when it is already paused or a claimed worktree has uncommitted work (commit it there as
"wip: <task> ..."), and until resume status asks for it, so the gate waits; the claims stay held, as each task
continues from its wip commit. Every pause also shows in notes as "paused: <text>", in ledger order, after resume too.
add --full on a qa run marks a run of the full suite (every test line of Comandos and the entire interface suite);
status --json gives the latest as full_qa. add --interface on a qa run marks one that ran the "Verificação de interface"
command on at least one path. When the CLAUDE.md at the ledger's root gives that line a command (not a _(...)_
placeholder), the first cycle closes only once one of its qa runs has --interface or --full: a machine that cannot run
it is a block to make ready, not a VALIDAR. Later cycles do not need it.

A cycle is a few dev tasks followed by one reviewer pass over their diff and one qa pass; the two run in parallel.
It closes when the latest reviewer PASS came after the latest dev run, qa PASSed after the cycle's latest regular
task, and qa ran again after every fix of a blocking (FAIL) finding. The next regular dev run opens the next cycle.
A fix round (task fix-N) and the cleanup task (task cleanup) stay in the current cycle, even a closed one: they need
a reviewer pass, and qa again only when a FAIL came before them. Every finding carries its origin (design,
assumption, plan, execution, environment); --report keeps the path of the file the manager saved the agent's report
in, so a FAIL still open names it, and is refused when no file is there (the agents have no Write: the manager saves
the report, then adds the run naming it), read from the current directory or from the ledger's project root; a qa --report must hold the Verdict:, Commit:,
Interface: and Processes: lines of qa.md's report (Verdict the one given, Commit a commit here), and the run
stores that commit as tested, and stale when it is not the latest dev run's head or later: a qa dispatched before a
fix counts only for what came before it, so its FAIL still asks for the fix and the re-run is still asked for; --seconds takes 90, 12m, 1h5m or 12m30s, and --seconds and --tokens are optional, from the
agent's completion notification when it already arrived, never an estimate (a run without them goes unmeasured, its
span counting from its timestamp in the cycle's elapsed, which is null when that span comes to zero, and 0 is refused). measure fills the numbers
of a run whose completion notification arrived after its add, as its own line naming that run: with one run of that
agent and task still unmeasured it takes them by itself, and with more than one it refuses and lists their at, which
--at then names (a waived run takes none, and a run already measured is refused) - guessing would move the numbers of
every later notification by one run, for the whole delivery. No dispatch ever waits for a notification. status lists
each run still with no seconds (unmeasured: agent, task, at, oldest first, a waived run left out) with the measure --at
that fills it, so a notification that arrived after a compaction is never lost. status gives each claim in flight its
waiting_minutes, partial_report (true from 90 minutes on: its line asks for a partial report by SendMessage) and, for a
claim with no worktree whose delivery head moved since, committed: the dev commits straight on the branch, so its work
may be in and its report waiting to be added. A deferred item with no decision keeps the delivery from the gate. Everything that waits for the user carries --recommend, what the manager would decide and why, so every list of what waits (status, the pane, validar) recommends without being asked: defer requires it, note takes it with --validar and refuses it without. An entry of an earlier version, with no recommendation, reads as before. start --archive moves an existing delivery to
ledger-<old-slug>.jsonl next to the ledger first. start also carries each item the latest quality report (the docs/quality-reports/*.md git added last at the ledger's project root, else the last by name) moved to a later delivery, a line of its Deferred section whose decision, after the first arrow, starts with "moved to" in any case, as a deferred item of the new delivery, recommending that decision, so it needs a decision before the gate and is never forgotten. --check exits 1 while anything is pending, so the gate can rely on
it. A cycle whose reviewer or qa still fails after a fix round asks the user; in autonomous mode the fix rounds go on
up to three, then the delivery stops. extend, once status asks the user or stops, records the user's decision to go
on (a note, VALIDAR in autonomous mode): the current cycle gets one more fix round, and a reviewer or qa FAIL after
it asks or stops again; it never carries to the next cycle. extend --task spec|plan is the same for that review loop,
which runs one more round (also when status says waive: the user overrules it), and each extension is read only by the loop (or the cycle) it was given to. With scope recorded, a task of a later plan cycle may be
claimed while the current cycle is open, but its add is refused until the cycle closes, so the next cycle's range
starts at the head that closed this one. waive is refused when the dev ran after that FAIL (the fix needs its review); it
records the reason as a note and counts as that agent's PASS at the head it reviewed. Notes marked --validar (and
waivers in autonomous mode) are listed apart, numbered V1, V2... in the order written, for the user to confirm on
return; validate records the decision, and status lists the items still waiting apart from the decided ones. A
ledger with no mode entry is supervised.

A reviewer run with --task spec or plan is one round of that review loop, before the code: it is no part of any
cycle, and its findings, time and tokens are counted apart in the metrics. --task security is the security scan of a
sensitive delivery, a loop of the same kind run after the last cycle (its open findings, after the 3rd FAIL, are
deferred with a decision instead of carried to the plan). While the latest round is a FAIL, status
asks for the next round, on the range from the head the failed round recorded (the corrections only), and every
later round of the loop needs --triage: what became of each finding of the previous round (applied, refused or carried
to the errata), counting every one of them once; the metrics sum the refused ones. A loop is the rounds since that
review's latest PASS (a waiver included), so a document reviewed again after a change of scope starts at round 1. After
the 3rd FAIL with no Critical open, in either mode, status says waive (carry the open findings to the plan's Errata, or
to the plan's brief for a spec, and waive --task) without asking the user; with a Critical open it asks the user, or
stops the delivery in autonomous mode. waive --task closes the loop.

status --json also gives the pending items as data and where the delivery is in its plan. claims: one {task, at,
worktree, origin, tip, head_moved} per task in flight; paused: {text, at} or null; full_qa: the latest qa run added with
--full, or null. from: the commit the current cycle's diff starts at, for the reviewer's and qa's range: the base for
cycle 1, else the head the run that closed the previous cycle recorded (a commit made after it and before this cycle's
first task, such as an errata, falls in the range too). steps: one {"step": resume|dev|reviewer|qa|fix|review|waive|ask|
stop|decide, ...} per pending item, with its detail (task and verdict, agent, open findings and the report path, a qa
re-run, a review round with its from and report, a review loop to waive, a deferred id and text, the pause text); a task in flight is no step. scope:
the plan cycles recorded with scope, in the order first recorded (a later scope for a cycle replaces its tasks in place, an empty one removes
it), each with the tasks that have no DONE run yet; the current cycle (the one holding the task in flight once the
open cycle has closed, else the latest task); and how many tasks and cycles are left (a cycle whose tasks are done
counts until it closes). scope.tasks gives each task of the scope, in order, with its cycle, goal and depends (the
Goal: and Depends on: lines of its section in the plan, the heading that names the task down to the next heading of
its level or above; null when the plan or the line is missing) and its state: done, running (with minutes), blocked
(a task of the scope its depends names is not done) or todo; scope.median_task_seconds is the median time of the
regular dev tasks done and measured, null before the first. With no scope recorded, scope is null.

mode autonomous --until records the time the user is back: HH:MM is the next time this machine's clock shows it
(tomorrow when it is past today), or an ISO time with its offset; a time already past, or --until in supervised mode,
is refused. While the latest mode entry carries it, status --json gives night: {until, seconds_left, expected, fits,
over, done_since}, else null. expected is each run's expected seconds from this delivery's measured runs, null before
the first: dev is scope's median_task_seconds, reviewer and qa the median of their cycle runs (qa without --full), and
qa_full the latest qa --full; fits says whether it ends before until (null when unknown). over is true once until is
reached or when no run fits; done_since is {tasks, runs}: the dev tasks done and the runs added since that mode entry,
for the morning summary. The text names what does not fit, not to be dispatched, and, once over, says to pause. It is
advice, never pending, like usage.

status also reads usage.json from the ledger's folder (the subscription windows the mod writes: five_hour and
seven_day, each {percent, resets_at}; a window past its resets_at, a missing or broken file and unknown fields are
ignored; a null resets_at counts as valid; a JSON error is retried once after 200 ms, as the mod's write is not
atomic; a file still broken is named once in the text) and the optional thresholds
in CLAUDE.local.md at the root of the ledger's worktree (Economia a partir de quanto uso, em %, default 60; Pausa a
partir de quanto uso da janela de 5 horas, em %, default 85; Pausa a partir de quanto uso da semana, em %, default
95; Sempre econômico, default não). A value counts only when it starts with a backtick and holds a number from 1 to
100 (sim or yes for Sempre econômico); a placeholder such as _(...)_ keeps the default. status --json gives usage:
{windows, economy, wait} or null: economy is the reason (a window at or above the economy threshold, or Sempre
econômico) or null; wait is the window whose percent plus its margin is at or above its pause threshold (the one that resets
later when both are) or null: {window, percent, margin, resets_at, seconds_left}. The margin is the largest of the
last 5 positive deltas between consecutive usage snapshots of the runs (a negative delta is a reset, skipped; 0 with
none), the room the next run may use. seconds_left, from now, is null when resets_at is; the text line ends with
"until <resets_at> (in 2h13m)". It is advice for the manager, never pending: pending, steps and ready_for_gate do not change. Every add records
the valid windows' percent as usage.

add --agent dev also stores diff {files, added, removed}, the size of the task's own commits (git diff --numstat; a
binary file counts as one file and no line). A worktree run is measured from the merge-base of the delivery head and
the worktree's tip (the claim's origin when that fails or is the tip itself, a task integrated by fast-forward before
its add), so a worktree rebased onto
later integrations counts only its own commits, to the tip, which the run stores as tip; the next dev run of the
same task starts at that stored tip when it is an ancestor of the new one and later than the merge-base, so wip
commits count once. A run with no worktree (or one that is gone) is measured from the head its live claim stored at
dispatch (claim stores head, the delivery head), so the spec, plan and errata commits are never charged; with no
claim head (an older ledger, or a run with no claim) from the head the previous run of any agent stored, the
delivery base for the first. On any git failure nothing is stored and the add goes on. add --agent dev --verdict
NEEDS_CONTEXT --simpler marks a simpler: proposal (any other agent or verdict refuses the flag) and stores
simpler: true. status --json gives metrics.lines: tasks {task: added+removed over its dev runs}, total, follow_up
(fix-N and cleanup), share (follow_up/total, 2 decimals, null at 0) and unmeasured (dev runs with no diff, as every
run of an older ledger); and metrics.verdicts: {needs_context, simpler, blocked} over the dev runs (simpler
proposals are not counted in needs_context; 0 for an older ledger). It is advice, never pending: pending, steps and
ready_for_gate do not change. metrics.time.delivery is the delivery's clock: {elapsed, from start to the latest
measured run with the pauses left out; paused; agents, the union of the measured runs, the time some agent was
running; share, agents over elapsed}, null before the first measured run.

capacity answers, before a dispatch that prepares or verifies, how many parallel copies fit: the free memory (Windows
GlobalMemoryStatusEx, Linux MemAvailable; PIPELINE_CAPACITY_MEMORY_GB and PIPELINE_CAPACITY_DISK_GB override the
measure, and an empty or invalid value counts as unknown) and the free disk of the worktree root, against the Execução
em paralelo lines of CLAUDE.local.md (peak of a copy, memory and disk; free-memory floor; heavy copies with the user
on the machine, which caps copies in supervised mode only; 0 is unknown). The template label wins; else the section's
free text: "mais de ~N GB livres" is the floor and "<N> cópia(s) pesada(s)" the heavy limit; the disk peak stops at the
first sentence end and "medir" is unknown. With the floor unknown, dispatch is null (exit 0) and the reason says which
line to fill. The reason names an env override that replaced a measure. copies is the largest n with free - n*peak >= max(peak,
floor), so one more copy and the floor stay free (null when the peak or the memory is unknown); dispatch is false below
the floor. It needs no delivery, exits 1 when dispatch is false, and --json gives memory_free_gb, disk_free_gb, peak_gb,
disk_peak_gb, floor_gb, heavy_limit, autonomous, dispatch, copies and reason.

Without --ledger, the ledger is .superpowers/ledger.jsonl at the root of the current worktree, or of the main
worktree when the current one has none (a task worktree), except for start, which always uses the current one. A
line that is not JSON stops every command with its line number, so a truncated write is never skipped silently."""
import argparse
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata

VERDICTS = {
    "discovery": {"DONE", "NEEDS_CONTEXT", "BLOCKED"},
    "dev": {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"},
    "reviewer": {"PASS", "FAIL"},
    "qa": {"PASS", "FAIL"},
}
ORIGINS = ("design", "assumption", "plan", "execution", "environment")
SEVERITIES = ("critical", "important", "minor")
FIX_ROUNDS = {False: 1, True: 3}
REVIEW_ROUNDS = 3
TRIAGE = ("applied", "refused", "errata")
REVIEWS = ("spec", "plan", "security")
PARTIAL_REPORT_MINUTES = 90
INTERFACE_LINE = re.compile(r"^- Verifica[çc][ãa]o de interface[^:\n]*:[ \t]*(.*)$", re.MULTILINE | re.IGNORECASE)
# Set by main from the project's CLAUDE.md: the first cycle closes only once a qa ran the interface.
NEEDS_INTERFACE = False
QUALITY_REPORTS = "docs/quality-reports"
MOVED = re.compile(r"- D\d+ (.*?) -> (moved to .*)", re.IGNORECASE)
DONE = ("DONE", "DONE_WITH_CONCERNS")
FIX_TASK = re.compile(r"fix-\d+", re.IGNORECASE)
FOLLOW_UP = re.compile(r"fix-\d+|cleanup", re.IGNORECASE)
DURATION = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?|(\d+)")
LEDGER = os.path.join(".superpowers", "ledger.jsonl")
EARLIEST = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
# The lines of qa.md's report that the ledger reads; a report that lacks one was not pasted as qa wrote it.
QA_LINES = ("Verdict", "Commit", "Interface", "Processes")


def git_head(rev="HEAD", ledger=None, tree=None):
    where = os.path.dirname(os.path.abspath(ledger)) if ledger else None
    for cwd in [tree] if tree else ([where] if where and os.path.isdir(where) else []) + [None]:
        result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", rev + "^{commit}"], capture_output=True,
                                text=True, cwd=cwd)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def git_path(*args):
    result = subprocess.run(["git", "rev-parse", *args], capture_output=True, text=True)
    return os.path.abspath(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def default_ledger(command):
    top = git_path("--show-toplevel")
    here = os.path.join(top, LEDGER) if top else LEDGER
    common = git_path("--git-common-dir")
    main = os.path.join(os.path.dirname(common), LEDGER) if common else here
    return here if os.path.exists(here) or command == "start" or not os.path.exists(main) else main


def read(path):
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except ValueError as error:
                sys.exit(f"{path}:{number}: not a ledger entry ({error}); fix or remove that line by hand")
    return folded(entries)


def folded(entries):
    """Every measure entry filled into the one run it names, so a batch of notifications arriving after several runs
    lands one number per run, whichever order they arrive in and even when a run was never measured at all."""
    held, kept = {}, []
    for entry in entries:
        if entry["type"] == "measure":
            target = completes(held.get((entry["agent"], entry.get("task") or ""), []), entry)
            for key in ("seconds", "tokens"):
                if target is not None and entry.get(key) is not None:
                    target[key] = entry[key]
            continue
        if entry["type"] == "run":
            held.setdefault((entry["agent"], entry.get("task") or ""), []).append(entry)
        kept.append(entry)
    return kept


def completes(runs, entry):
    """The run a measure entry completes: the one its at_run names, or, in an entry written before 1.9.9 (which named
    none), the latest of them, as that version filled it — so a ledger of those versions reads as it did."""
    if entry.get("at_run"):
        return next((run for run in runs if run.get("at") == entry["at_run"]), None)
    return runs[-1] if runs else None


def write(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def is_review(entry):
    return entry["agent"] == "reviewer" and (entry.get("task") or "") in REVIEWS


def runs(entries):
    return [entry for entry in entries if entry["type"] == "run" and not is_review(entry)]


def reviews(entries, task=None):
    return [entry for entry in entries if entry["type"] == "run" and is_review(entry) and task in (None, entry["task"])]


def is_task(entry, pattern):
    return entry["agent"] == "dev" and bool(pattern.fullmatch(entry.get("task") or ""))


def where(entry):
    return f", report {entry['report']}" if entry.get("report") else ""


def saved_report(path, ledger):
    root = os.path.dirname(os.path.dirname(os.path.abspath(ledger)))
    return os.path.isfile(path) or os.path.isfile(os.path.join(root, path))


def advice_of(entry):
    return {"recommend": entry["recommend"]} if entry.get("recommend") else {}


def report_of(entry):
    return {"report": entry["report"]} if entry.get("report") else {}


def interface_line(ledger):
    """True when the project's CLAUDE.md, at the ledger's root, gives a Verificação de interface command."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(ledger))), "CLAUDE.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    section = re.split(r"^## ", text, flags=re.MULTILINE)
    comandos = next((part for part in section if part.lower().startswith("comandos")), "")
    match = INTERFACE_LINE.search(comandos)
    value = match.group(1).strip() if match else ""
    return bool(value) and not value.startswith("_(")


def first(groups):
    """The interface a cycle needs: only the first one, and only when the project has the line."""
    return NEEDS_INTERFACE and len(groups) == 1


def cycles(entries):
    groups, current, closed = [], [], False
    for entry in runs(entries):
        if closed and entry["agent"] == "dev" and not is_task(entry, FOLLOW_UP):
            groups.append(current)
            current, closed = [], False
        current.append(entry)
        closed = cycle_state(current, interface=NEEDS_INTERFACE and not groups)[1] == []
    groups.append(current)
    return groups


def extension(entries, group, task=None):
    """How many runs of the group (a cycle, or a review loop with its task) came before the latest extend given to it."""
    marks = [index for index, entry in enumerate(entries) if entry["type"] == "extend" and entry.get("task") == task]
    position = {id(entry): index for index, entry in enumerate(entries)}
    if not marks or not group or marks[-1] < position[id(group[0])]:
        return None
    return sum(1 for entry in group if position[id(entry)] < marks[-1])


def cycle_state(cycle, autonomous=False, extended=None, interface=False):
    tasks, reviews, checks = {}, [], []
    work = last_dev = last_review = last_qa = seen_qa = needs_qa = -1
    for index, entry in enumerate(cycle):
        if entry["agent"] == "dev":
            tasks[entry["task"]] = entry
            if not is_task(entry, FOLLOW_UP):
                work = index
            if any(run["verdict"] == "FAIL" for run in cycle[last_dev + 1:index] if run["agent"] in ("reviewer", "qa")):
                needs_qa = index
            last_dev = index
        elif entry["agent"] == "reviewer":
            reviews.append(entry)
            last_review = index
        elif entry["agent"] == "qa":
            checks.append(entry)
            seen_qa = index
            # A qa that tested a commit before the latest dev run (dispatched before the fix) covers what came before it.
            last_qa = last_dev - 0.5 if entry.get("stale") else index
    pending, steps = [], []
    state = {"tasks": tasks, "reviewer": reviews[-1:], "qa": checks[-1:], "steps": steps}

    def need(text, step, **detail):
        pending.append(text)
        steps.append({"step": step, **detail})

    for task, entry in tasks.items():
        if entry["verdict"] not in DONE:
            need(f"dev {task}: {entry['verdict']}", "dev", task=task, verdict=entry["verdict"])
    if not tasks:
        need("no dev task yet", "dev")
    if pending:
        return state, pending
    if last_review < last_dev:
        need("reviewer has not reviewed the latest changes", "reviewer")
    elif reviews[-1]["verdict"] == "FAIL":
        need(f"reviewer FAIL ({reviews[-1]['open']} open{where(reviews[-1])}): dev fixes every finding in one batch",
             "fix", agent="reviewer", open=reviews[-1]["open"], **report_of(reviews[-1]))
    if not checks or last_qa < work:
        need("qa has not run on the cycle's tasks", "qa")
    elif checks[-1]["verdict"] == "FAIL" and seen_qa > last_dev:
        need(f"qa FAIL ({checks[-1]['open']} open{where(checks[-1])}): dev fixes every finding in one batch",
             "fix", agent="qa", open=checks[-1]["open"], **report_of(checks[-1]))
    elif last_qa < needs_qa:
        need("qa has not re-run the scenarios the fix touched", "qa", rerun=True)
    elif interface and not any(entry.get("interface") or entry.get("full") for entry in checks):
        need("cycle 1 closes only once a qa ran the interface (Verificação de interface) on at least one path: open, "
             "sign in, a screen with data; add it with --interface. A machine that cannot run it is a block, never a "
             "VALIDAR: make it ready (Preparar uma máquina) first", "qa", interface=True)
    rounds = FIX_ROUNDS[autonomous] if extended is None else 0
    for agent, done in (("reviewer", reviews), ("qa", checks)):
        failed = sum(1 for index, entry in enumerate(cycle) if index >= (extended or 0) and entry["agent"] == agent
                     and entry["verdict"] == "FAIL")
        if done and done[-1]["verdict"] == "FAIL" and failed > rounds:
            if extended is not None:
                need(f"{agent} still fails after the extra fix round: "
                     + ("stop the delivery and record the open findings as note --validar" if autonomous
                        else "ask the user"), "stop" if autonomous else "ask", agent=agent, extended=True,
                     rounds=sum(1 for entry in done if entry["verdict"] == "FAIL") - 1)
            elif autonomous:
                need(f"{agent} still fails after {rounds} fix rounds: stop the delivery and record the open "
                     "findings as note --validar", "stop", agent=agent, rounds=rounds)
            else:
                need(f"{agent} still fails after a fix round: ask the user", "ask", agent=agent)
    return state, pending


def review_loop(entries, task):
    """The rounds of that review since its latest PASS (a waiver included): a document reviewed again after a PASS, as
    after a change of scope, starts a new loop at round 1."""
    done = reviews(entries, task)
    passed = [index for index, entry in enumerate(done) if entry["verdict"] == "PASS"]
    return done[passed[-1] + 1:] if passed else done


def review_state(entries, autonomous=False):
    pending, steps = [], []
    for task in REVIEWS:
        loop = review_loop(entries, task)
        if not loop:
            continue
        extended = extension(entries, loop, task)
        last, rounds = loop[-1], len(loop)
        mark = {"extended": True} if extended is not None else {}
        after = "the extra round" if extended is not None else f"{rounds} rounds"
        if rounds < (REVIEW_ROUNDS if extended is None else extended + 1):
            head = last.get("head")
            text = (f"{task} review round {rounds} FAIL ({last['open']} open{where(last)}): "
                    + ("send each finding to the dev as a fix-N or defer it, then scan " if task == "security" else
                       f"triage every finding (applied, refused or errata), commit the {task} and dispatch the "
                       "reviewer on ")
                    + (f"{head[:12]}..HEAD, the corrections only" if head else "the corrections only"))
            steps.append({"step": "review", "task": task, "round": rounds + 1, "open": last["open"],
                          **({"from": head} if head else {}), **report_of(last)})
        elif last.get("critical") == 0:
            text = (f"{task} review still fails after {after} with no Critical: "
                    + ("defer each open finding with a decision" if task == "security" else
                       "carry each open finding to the " + ("plan's Errata" if task == "plan" else "plan's brief"))
                    + f" and waive --task {task}; extend only on the user's word")
            steps.append({"step": "waive", "task": task, "rounds": rounds, "open": last["open"], **report_of(last),
                          **mark})
        else:
            text = f"{task} review still fails after {after}: " + (
                "stop the delivery and record the open findings as note --validar" if autonomous else "ask the user")
            steps.append({"step": "stop" if autonomous else "ask", "task": task, "rounds": rounds, **mark})
        pending.append(text)
    return pending, steps


def cycle_from(entries, groups):
    previous = groups[-2] if len(groups) > 1 else []
    return (previous[-1].get("head") or None) if previous else entries[0].get("base")


def archive_path(ledger, slug):
    name = "ledger-" + re.sub(r"[^\w.-]+", "-", slug or "delivery")
    stem = os.path.join(os.path.dirname(os.path.abspath(ledger)), name)
    path, number = stem + ".jsonl", 1
    while os.path.exists(path):
        number += 1
        path = f"{stem}-{number}.jsonl"
    return path


def start(args):
    entries = read(args.ledger)
    if entries and not args.archive:
        sys.exit(f"{args.ledger} already has a delivery ({entries[0].get('slug')}); "
                 "run start --archive to move it to ledger-<slug>.jsonl and start fresh")
    base = git_head(args.base, args.ledger)
    if base is None:
        sys.exit(f"not a commit: {args.base}")
    if entries:
        target = archive_path(args.ledger, entries[0].get("slug"))
        os.replace(args.ledger, target)
        print(f"archived {entries[0].get('slug')} to {target}")
    write(args.ledger, {"type": "start", "slug": args.slug, "base": base, "plan": args.plan})
    print(f"started {args.slug} at {base[:12]}")
    report, moved = carried(args.ledger)
    for number, (text, decision) in enumerate(moved, 1):
        write(args.ledger, {"type": "defer", "id": f"D{number}", "text": f"{text} (moved here by {report})",
                            "recommend": f"decide whether this delivery takes it: {decision}"})
    if moved:
        print(f"carried {len(moved)} items moved to a later delivery from {report}: each needs a decision "
              "before the gate (resolve --id)")


def carried(ledger):
    """The items the latest quality report moved to a later delivery: (report path, [(text, decision)]). The latest is
    the one git added last (two reports of one day sort by slug, and a clone keeps no file times), else the last by
    name; the decision starts at the first arrow followed by "moved to", in any case."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(ledger)))
    folder = os.path.join(root, *QUALITY_REPORTS.split("/"))
    names = sorted(name for name in os.listdir(folder) if name.endswith(".md")) if os.path.isdir(folder) else []
    if not names:
        return None, []
    result = subprocess.run(["git", "log", "-1", "--diff-filter=A", "--format=", "--name-only", "-z", "--",
                             QUALITY_REPORTS], capture_output=True, text=True, encoding="utf-8", cwd=root)
    added = [os.path.basename(path) for path in result.stdout.split("\0")] if result.returncode == 0 else []
    latest = max((name for name in added if name in names), default=names[-1])
    section, moved = False, []
    with open(os.path.join(folder, latest), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("## "):
                section = line.strip() == "## Deferred"
            elif section and (match := MOVED.fullmatch(line.strip())):
                moved.append(match.groups())
    return f"{QUALITY_REPORTS}/{latest}", moved


def seconds(text):
    match = DURATION.fullmatch(text.strip()) if text and text.strip() else None
    if not match or not any(match.groups()):
        sys.exit(f"--seconds must look like 90, 12m, 1h5m or 12m30s, not {text!r}")
    hours, minutes, rest, bare = (int(part or 0) for part in match.groups())
    total = hours * 3600 + minutes * 60 + rest + bare
    if total == 0:
        sys.exit("--seconds 0 is no measurement: leave it out when the run went unmeasured")
    return total


def tally(flag, names, text, total):
    """<name>=N,... counts that must add up to total, every finding counted once (--origin, --triage)."""
    counts = {}
    for item in filter(None, (part.strip() for part in (text or "").split(","))):
        name, _, number = (piece.strip() for piece in item.partition("="))
        if name not in names or not number.isdigit():
            sys.exit(f"{flag} takes <name>=N with name one of {', '.join(names)}, not {item!r}")
        counts[name] = counts.get(name, 0) + int(number)
    if sum(counts.values()) != total:
        sys.exit(f"{flag} must count every finding once: {sum(counts.values())} counted, {total} findings")
    return counts


def usage_files(ledger):
    folder = os.path.dirname(os.path.abspath(ledger))
    return os.path.join(folder, "usage.json"), os.path.join(os.path.dirname(folder), "CLAUDE.local.md")


def usage_settings(path):
    """CLAUDE.local.md thresholds: a value counts only when it starts with a backtick (a placeholder starts with _()."""
    found = {"economy": 60, "five_hour": 85, "seven_day": 95, "always": False}
    labels = {"economia a partir de quanto uso, em %": "economy",
              "pausa a partir de quanto uso da janela de 5 horas, em %": "five_hour",
              "pausa a partir de quanto uso da semana, em %": "seven_day", "sempre economico": "always"}
    try:
        with open(path, encoding="utf-8") as handle:
            rows = handle.read().splitlines()
    except (OSError, ValueError):
        return found
    for row in rows:
        plain = "".join(c for c in unicodedata.normalize("NFD", row.lower()) if not unicodedata.combining(c))
        for label, key in labels.items():
            head, colon, rest = plain.partition(":")
            if colon and head.strip(" -*") == label and rest.strip().startswith("`"):
                value = rest.strip()[1:].partition("`")[0].strip()
                if key == "always":
                    found[key] = value in ("sim", "yes")
                elif re.fullmatch(r"\d+(\.\d+)?", value) and 1 <= float(value) <= 100:
                    found[key] = float(value)
    return found


def usage_windows(ledger):
    """The windows of usage.json still valid, and whether the file was unreadable. Never raises."""
    path = usage_files(ledger)[0]
    if not os.path.exists(path):
        return {}, False
    try:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except ValueError:  # the mod's write is not atomic: a half-written file may be valid a moment later
            time.sleep(0.2)
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        now, valid = datetime.datetime.now(datetime.timezone.utc), {}
        for name in ("five_hour", "seven_day"):
            item = data["windows"].get(name)
            if (not isinstance(item, dict) or isinstance(item.get("percent"), bool)
                    or not isinstance(item.get("percent"), (int, float))):
                continue
            reset = reset_at(item)
            if reset is None or reset > now:
                valid[name] = {"percent": item["percent"], "resets_at": item.get("resets_at")}
        return valid, False
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}, True


def reset_at(item):
    """When the window resets, or None when unknown (null, missing or unreadable): the window then counts as valid.
    Z and any fraction are normalized first, as fromisoformat before Python 3.11 rejects both."""
    text = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), str(item.get("resets_at") or ""))
    try:
        reset = datetime.datetime.fromisoformat(re.sub(r"[zZ]$", "+00:00", text.strip()))
    except ValueError:
        return None
    return reset if reset.tzinfo else reset.replace(tzinfo=datetime.timezone.utc)


def usage_margins(entries):
    """Per window, the largest of the last 5 positive deltas between consecutive usage snapshots of the runs (a
    negative delta is a reset in between); 0 with none."""
    last, deltas = {}, {}
    for entry in runs(entries):
        for name, percent in (entry.get("usage") or {}).items():
            if isinstance(percent, bool) or not isinstance(percent, (int, float)):
                continue
            if name in last and percent > last[name]:
                deltas.setdefault(name, []).append(percent - last[name])
            last[name] = percent
    return {name: max(found[-5:]) for name, found in deltas.items()}


def usage_advice(windows, settings, margins=None):
    margins = margins or {}
    economy = next((f"{name} at {int(item['percent'])}%" for name, item in windows.items()
                    if item["percent"] >= settings["economy"]), None)
    economy = economy or ("always (CLAUDE.local.md)" if settings["always"] else None)
    over = [(name, item) for name, item in windows.items()
            if item["percent"] + margins.get(name, 0) >= settings[name]]
    name, item = max(over, key=lambda pair: reset_at(pair[1]) or EARLIEST) if over else (None, None)
    wait = None
    if name:
        reset = reset_at(item)
        now = datetime.datetime.now(datetime.timezone.utc)
        wait = {"window": name, "percent": item["percent"], "margin": margins.get(name, 0),
                "resets_at": item["resets_at"],
                "seconds_left": max(0, int((reset - now).total_seconds())) if reset else None}
    if not windows and not economy:
        return None
    return {"windows": windows, "economy": economy, "wait": wait}


def diff_size(old, new, cwd):
    if not old or not new:
        return None
    result = subprocess.run(["git", "diff", "--numstat", old, new], capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        return None
    size = {"files": 0, "added": 0, "removed": 0}
    for line in result.stdout.splitlines():
        added, removed = line.split(chr(9))[:2]
        size["files"] += 1
        size["added"] += int(added) if added.isdigit() else 0
        size["removed"] += int(removed) if removed.isdigit() else 0
    return size


def git_ok(cwd, *args):
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip() if result.returncode == 0 else None


def task_diff(entries, task, head, ledger):
    """The size of the task's own commits and, for a worktree, the tip it was measured at."""
    held = claims(entries).get(task)
    if held and held.get("worktree") and os.path.isdir(held["worktree"]):
        tree, end = held["worktree"], tip(held)
        start = git_ok(tree, "merge-base", head, end) if head and end else None
        # A tip already in the head (integrated by fast-forward before the add) is its own merge-base: no lines.
        if not start or start == end:
            start = held.get("origin") or start
        stored = [entry["tip"] for entry in entries if entry["type"] == "run" and entry.get("agent") == "dev"
                  and entry.get("task") == task and entry.get("tip")]
        if start and end and stored and git_ok(tree, "merge-base", "--is-ancestor", stored[-1], end) is not None \
                and git_ok(tree, "merge-base", "--is-ancestor", start, stored[-1]) is not None:
            start = stored[-1]
        return diff_size(start, end, tree), end
    previous = [entry["head"] for entry in entries if entry["type"] == "run" and entry.get("head")]
    base = [entry.get("base") for entry in entries if entry["type"] == "start"]
    where = os.path.dirname(os.path.abspath(ledger))
    start = (held or {}).get("head") if held and not held.get("worktree") else None
    return diff_size(start or (previous[-1] if previous else (base[-1] if base else None)), head,
                     where if os.path.isdir(where) else None), None


def add(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.verdict not in VERDICTS[args.agent]:
        sys.exit(f"{args.agent} verdict must be one of {', '.join(sorted(VERDICTS[args.agent]))}")
    if args.agent == "dev" and not args.task:
        sys.exit("dev runs need --task")
    if args.agent != "dev" and args.task and not (args.agent == "reviewer" and args.task in REVIEWS):
        sys.exit("--task on a reviewer run is spec, plan or security (one round of that review loop); qa runs take "
                 "none")
    if args.agent == "dev" and args.report:
        sys.exit("--report keeps the file of a reviewer or qa report; the dev's report is checked before integrating")
    if args.report and not saved_report(args.report, args.ledger):
        sys.exit(f"--report {args.report} is no file: the agents have no Write, so save the report there yourself "
                 "and add the run naming the file you saved")
    if args.full and args.agent != "qa":
        sys.exit("--full marks a qa run of the project's full test command")
    if args.interface and args.agent != "qa":
        sys.exit("--interface marks a qa run that ran the interface (Verificação de interface)")
    if args.simpler and not (args.agent == "dev" and args.verdict == "NEEDS_CONTEXT"):
        sys.exit("--simpler marks a dev NEEDS_CONTEXT run that proposes a simpler way (a simpler: proposal)")
    loop = review_loop(entries, args.task) if args.agent == "reviewer" and args.task in REVIEWS else []
    if loop and args.triage is None:
        sys.exit(f"round {len(loop) + 1} of the {args.task} review needs --triage applied=N,refused=N,errata=N: what "
                 f"became of each finding of round {len(loop)}, so the next round reviews only the corrections")
    if args.triage is not None and not loop:
        sys.exit("--triage counts the findings of the previous round of a spec or plan review that failed")
    blocking = args.critical + args.important
    if args.agent in ("reviewer", "qa") and (args.verdict == "FAIL") != (blocking > 0):
        sys.exit("FAIL needs open Critical/Important findings (--critical or --important > 0) and PASS none")
    if args.agent == "dev" and not FOLLOW_UP.fullmatch(args.task):
        groups = cycles(entries)
        cycle = groups[-1]
        later = later_cycle(entries, cycle, args.task) if cycle_state(cycle, interface=first(groups))[1] else None
        if later:
            sys.exit(f"{args.task} is a task of plan cycle {later}: integrate and add it once this cycle closes "
                     "(status says what the cycle still needs), so the next cycle's range starts where this one ends")
    entry = {"type": "run", "agent": args.agent, "task": args.task, "verdict": args.verdict, "open": blocking,
             "critical": args.critical, "important": args.important, "minor": args.minor,
             "origin": tally("--origin", ORIGINS, args.origin, blocking + args.minor),
             "head": git_head(ledger=args.ledger) or ""}
    if args.report:
        entry["report"] = args.report
    if args.report and args.agent == "qa":
        entry.update(qa_report(args, entries))
    if loop:
        entry["triage"] = tally("--triage", TRIAGE, args.triage, sum(loop[-1].get(key) or 0 for key in SEVERITIES))
    if args.full:
        entry["full"] = True
    if args.interface:
        entry["interface"] = True
    if args.seconds is not None:
        entry["seconds"] = seconds(args.seconds)
    if args.tokens is not None:
        if args.tokens == 0:
            sys.exit("--tokens 0 is no measurement: leave it out when the run went unmeasured")
        entry["tokens"] = args.tokens
    if args.agent == "dev":
        try:
            size, end = task_diff(entries, args.task, entry["head"], args.ledger)
        except (OSError, ValueError):
            size, end = None, None
        if size:
            entry["diff"] = size
            if end:
                entry["tip"] = end
        if args.simpler:
            entry["simpler"] = True
    windows = usage_windows(args.ledger)[0]
    if windows:
        entry["usage"] = {name: item["percent"] for name, item in windows.items()}
    write(args.ledger, entry)
    label = f"{args.agent}{' ' + args.task if args.task else ''}: {args.verdict}"
    print(f"{label} (round {len(review_loop(read(args.ledger), args.task))})" if is_review(entry)
          else f"{label} (cycle {len(cycles(read(args.ledger)))})")


def qa_report(args, entries):
    """The tested commit of a saved qa report, refused when a line of qa.md's report is missing or disagrees; stale
    when it is not the latest dev run's head or later (qa was dispatched before that run, as before a fix)."""
    path = args.report if os.path.isfile(args.report) else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(args.ledger))), args.report)
    text = open(path, encoding="utf-8", errors="replace").read()
    found = {key: value.strip() for key, value in re.findall(
        r"(?im)^[ \t>*_-]*(" + "|".join(QA_LINES) + r")[*_]*:[*_]*[ \t]*(.*)$", text)}
    found = {key.capitalize(): value for key, value in found.items()}
    missing = [key + ":" for key in QA_LINES if key not in found]
    if missing:
        sys.exit(f"{args.report} lacks {', '.join(missing)} of qa.md's report: save the report as qa wrote it, or send "
                 "qa back for the lines it left out")
    said = found["Verdict"].split()[0].strip("*_`") if found["Verdict"] else ""
    if said.upper() != args.verdict:
        sys.exit(f"{args.report} says Verdict: {said or '(nothing)'}, not {args.verdict}")
    commit = found["Commit"].split()[0].strip("`") if found["Commit"] else ""
    tested = git_head(commit, args.ledger) if commit else None
    if not tested:
        sys.exit(f"{args.report} gives Commit: {commit or '(nothing)'}, which is no commit here")
    devs = [entry for entry in runs(entries) if entry["agent"] == "dev" and entry.get("head")]
    where = os.path.dirname(os.path.dirname(os.path.abspath(args.ledger)))
    stale = bool(devs) and subprocess.run(["git", "merge-base", "--is-ancestor", devs[-1]["head"], tested],
                                          capture_output=True, cwd=where).returncode == 1
    return {"tested": tested, **({"stale": True} if stale else {})}


def claims(entries):
    held = {}
    for entry in entries:
        if entry["type"] == "claim":
            held[entry["task"]] = entry
        elif entry["type"] == "release" or (entry["type"] == "run" and entry["agent"] == "dev"):
            held.pop(entry.get("task"), None)
    return held


def in_flight(entries):
    return {task: entry["at"] for task, entry in claims(entries).items()}


def place(entry, separator):
    origin = (entry.get("origin") or "")[:12]
    tree = f" in {entry['worktree']}" if entry.get("worktree") else ""
    return tree + (f"{separator if tree else ' '}from {origin}" if origin else "")


def tip(entry):
    tree = entry.get("worktree")
    return git_head(tree=tree) if tree and os.path.isdir(tree) else None


def moved(entry, head):
    return bool(entry.get("origin") and head and entry["origin"] != head)


def waiting(entry, now=None):
    """Minutes since the claim was written, or None when its timestamp is unreadable."""
    try:
        at = datetime.datetime.fromisoformat(entry["at"])
    except (KeyError, TypeError, ValueError):
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return max(0, int((now - at).total_seconds() // 60))


def committed(entry, head):
    """True when the delivery head moved since a claim with no worktree: the dev commits straight on the branch."""
    return bool(not entry.get("worktree") and entry.get("head") and head and entry["head"] != head)


def claim(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    held = in_flight(entries)
    if args.task in held:
        sys.exit(f"{args.task} is already claimed ({held[args.task]}): its dev run is in flight; "
                 f"if that run was lost, release --task {args.task}")
    groups = cycles(entries)
    done = cycle_state(groups[-1], interface=first(groups))[0]["tasks"].get(args.task)
    if done and done["verdict"] in DONE:
        sys.exit(f"{args.task} is already done in cycle {len(groups)}: use a new task id (fix-N for a fix round)")
    where = {}
    if args.worktree:
        if not os.path.isdir(args.worktree):
            sys.exit(f"--worktree {args.worktree} is no directory")
        where["worktree"] = os.path.abspath(args.worktree)
    if args.origin:
        where["origin"] = git_head(args.origin, args.ledger, where.get("worktree"))
        if where["origin"] is None:
            sys.exit(f"--origin is not a commit: {args.origin}")
    write(args.ledger, {"type": "claim", "task": args.task, **where, "head": git_head(ledger=args.ledger) or ""})
    print(f"claimed {args.task}")


def release(args):
    if args.task not in in_flight(read(args.ledger)):
        sys.exit(f"{args.task} has no claim in flight")
    write(args.ledger, {"type": "release", "task": args.task})
    print(f"released {args.task}")


def paused(entries):
    state = None
    for entry in entries:
        if entry["type"] == "pause":
            state = {"text": entry["text"], "at": entry["at"]}
        elif entry["type"] == "resume":
            state = None
    return state


def uncommitted(held):
    found = []
    for task, entry in held.items():
        tree = entry.get("worktree")
        if not tree or not os.path.isdir(tree):
            continue
        result = subprocess.run(["git", "-C", tree, "status", "--porcelain"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            found.append(f'{task}: uncommitted work in {tree}: commit it there as "wip: {task} <what is done>" first')
    return found


def pause(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if paused(entries):
        sys.exit(f"the delivery is already paused ({paused(entries)['text']}): resume first")
    dirty = uncommitted(claims(entries))
    if dirty:
        sys.exit("\n".join(dirty))
    write(args.ledger, {"type": "pause", "text": args.text})
    print(f"paused: {args.text}")


def resume(args):
    entries = read(args.ledger)
    if not paused(entries):
        sys.exit("the delivery is not paused")
    write(args.ledger, {"type": "resume"})
    print("resumed")
    for task, entry in claims(entries).items():
        at = tip(entry)
        print(f"- {task}" + (f" in {entry['worktree']}" if entry.get("worktree") else "")
              + (f" at {at[:12]}" if at else ""))


def note(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    if args.recommend and not args.validar:
        sys.exit("--recommend goes with --validar: a plain note records what is already decided and waits for nobody")
    if args.validar and not args.recommend:
        sys.exit("--validar needs --recommend: say what you would decide and why, so the user reads the item and the "
                 "recommendation together")
    entry = {"type": "note", "text": args.text}
    if args.validar:
        entry["validar"] = True
        entry["recommend"] = args.recommend
    write(args.ledger, entry)
    print("noted (VALIDAR)" if args.validar else "noted")


def validar(entries):
    items, decisions = [], {}
    for entry in entries:
        if entry["type"] == "note" and entry.get("validar"):
            items.append({"id": f"V{len(items) + 1}", "text": entry["text"], "decision": None,
                          **advice_of(entry)})
        elif entry["type"] == "validate":
            decisions[entry["id"]] = entry["decision"]
    for item in items:
        item["decision"] = decisions.get(item["id"])
    return items


def measure(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.agent == "dev" and not args.task:
        sys.exit("dev runs need --task")
    if args.agent != "dev" and args.task and not (args.agent == "reviewer" and args.task in REVIEWS):
        sys.exit("--task on a reviewer run is spec, plan or security (one round of that review loop); qa runs take none")
    numbers = {}
    if args.seconds is not None:
        numbers["seconds"] = seconds(args.seconds)
    if args.tokens is not None:
        numbers["tokens"] = args.tokens
    if not numbers:
        sys.exit("measure takes --seconds, --tokens or both, from the run's completion notification")
    if 0 in numbers.values():
        sys.exit("0 is no measurement: leave that number out while the run is unmeasured")
    which = f" of {args.task}" if args.task else ""
    # read() already folded the earlier measures in, so a run still missing a number is one no notification filled.
    found = [entry for entry in entries if entry["type"] == "run" and entry["agent"] == args.agent
             and (entry.get("task") or "") == args.task and entry.get("waived") is None]
    if not found:
        sys.exit(f"no {args.agent} run{which} in the ledger to complete")
    if args.at:
        named = [entry for entry in found if entry.get("at") == args.at]
        if not named:
            sys.exit(f"no {args.agent} run at {args.at}: status --json gives the at of each run, and a run the waive "
                     "dispensed takes no numbers")
        if len(named) > 1:
            # at is stamped to the second: runs that share one are indistinguishable here and to whoever reads it.
            sys.exit(f"{len(named)} {args.agent} runs share the at {args.at}: nothing here tells them apart, so leave "
                     "them unmeasured rather than put the numbers on a guess")
        target = named[0]
    else:
        open_runs = [entry for entry in found if any(entry.get(key) is None for key in numbers)]
        if not open_runs:
            sys.exit(f"every {args.agent} run{which} is already measured for {', '.join(numbers)}: the numbers come "
                     "from one completion notification, never a second guess")
        if len(open_runs) > 1:
            # Guessing moves the numbers of every later notification by one run, silently, for the whole delivery.
            sys.exit(f"{len(open_runs)} {args.agent} runs{which} are still missing {', '.join(numbers)}: pass --at "
                     "<timestamp> to name the one this notification completes "
                     f"({', '.join(entry['at'] for entry in open_runs)})")
        target = open_runs[0]
    already = [key for key in numbers if target.get(key) is not None]
    if already:
        sys.exit(f"that {args.agent} run is already measured ({', '.join(f'{key} {target[key]}' for key in already)}"
                 "): the numbers come from one completion notification, never a second guess")
    write(args.ledger, {"type": "measure", "agent": args.agent, "task": args.task, "at_run": target["at"], **numbers})
    print(f"measured {args.agent}{' ' + args.task if args.task else ''}: "
          + ", ".join(f"{key} {value}" for key, value in numbers.items()))


def validate(args):
    entries = read(args.ledger)
    if args.id not in {item["id"] for item in validar(entries)}:
        sys.exit(f"no VALIDAR item {args.id}")
    if not args.decision.strip():
        sys.exit("--decision needs the user's answer, not an empty text")
    write(args.ledger, {"type": "validate", "id": args.id, "decision": args.decision})
    print(f"{args.id} validated")


def waive(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.task:
        if args.agent != "reviewer":
            sys.exit("--task names a spec, plan or security review loop, which only the reviewer runs")
        done = reviews(entries, args.task)
        if not done or done[-1]["verdict"] != "FAIL":
            sys.exit(f"the latest {args.task} review is not a FAIL: nothing to waive")
        failed = done[-1]
    else:
        cycle = cycles(entries)[-1]
        done = [index for index, entry in enumerate(cycle) if entry["agent"] == args.agent]
        if not done or cycle[done[-1]]["verdict"] != "FAIL":
            sys.exit(f"the latest {args.agent} run of the cycle is not a FAIL: nothing to waive")
        if any(entry["agent"] == "dev" for entry in cycle[done[-1] + 1:]):
            sys.exit(f"the dev ran after that {args.agent} FAIL: run the {args.agent} on the fix to review it instead")
        failed = cycle[done[-1]]
    text = f"waived {args.agent} {args.task + ' ' if args.task else ''}FAIL: {args.reason}"
    write(args.ledger, {"type": "note", "text": text, **({"validar": True} if autonomous(entries) else {})})
    write(args.ledger, {"type": "run", "agent": args.agent, "task": args.task, "verdict": "PASS", "open": 0,
                        "critical": 0, "important": 0, "minor": 0, "origin": {}, "head": failed.get("head", ""),
                        "waived": args.reason})
    print(text)


def extend(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    if args.task:
        steps = review_state(entries, autonomous(entries))[1]
        if not any(step["step"] in ("stop", "ask", "waive") and step.get("task") == args.task for step in steps):
            sys.exit(f"the {args.task} review has not run out of rounds: nothing to extend")
        text = f"extra {args.task} review round: {args.reason}"
    else:
        groups = cycles(entries)
        cycle = groups[-1]
        state = cycle_state(cycle, autonomous(entries), extension(entries, cycle), first(groups))[0]
        if not any(step["step"] in ("stop", "ask") for step in state["steps"]):
            sys.exit("the cycle has not run out of fix rounds: nothing to extend")
        text = f"extra fix round: {args.reason}"
    write(args.ledger, {"type": "note", "text": text, **({"validar": True} if autonomous(entries) else {})})
    write(args.ledger, {"type": "extend", **({"task": args.task} if args.task else {}), "reason": args.reason})
    print(text)


def plan(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "plan", "plan": args.path})
    print(f"plan {args.path}")


def scope(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    tasks = [task.strip() for task in args.tasks.split(",") if task.strip()]
    write(args.ledger, {"type": "scope", "cycle": args.cycle, "tasks": tasks})
    print(f"cycle {args.cycle}: {len(tasks)} tasks" if tasks else f"cycle {args.cycle} removed from the scope")


def plan_cycles(entries):
    plan = {}
    for entry in entries:
        if entry["type"] == "scope":
            plan[entry["cycle"]] = entry["tasks"]
    return {cycle: tasks for cycle, tasks in plan.items() if tasks}


def later_cycle(entries, cycle, task):
    plan = plan_cycles(entries)
    names = list(plan)

    def position(name):
        return next((index for index, cycle_name in enumerate(names) if name in plan[cycle_name]), None)
    current = [position(entry["task"]) for entry in cycle if entry["agent"] == "dev" and not is_task(entry, FOLLOW_UP)]
    current = [index for index in current if index is not None]
    target = position(task)
    return names[target] if current and target is not None and target > current[-1] else None


def plan_text(entries, ledger):
    plans = [entry["plan"] for entry in entries if entry["type"] == "plan"] or [entries[0].get("plan")]
    root = os.path.dirname(os.path.dirname(os.path.abspath(ledger)))
    for path in ([plans[-1], os.path.join(root, plans[-1])] if plans[-1] else []):
        try:
            return open(path, encoding="utf-8").read()
        except OSError:
            continue
    return ""


def plan_field(text, task, name):
    """The task's Goal: or Depends on: line, from its heading to the next heading of the same level or above."""
    heading = re.search(r"^(#+)[ \t]+[*_`]*" + re.escape(task) + r"(?![\w-]|\.\w)[^\n]*$", text, re.MULTILINE)
    if not heading:
        return None
    level = len(heading.group(1))
    rest = text[heading.end():]
    end = re.search(r"^#{1,%d}[ \t]" % level, rest, re.MULTILINE)
    section = rest[:end.start()] if end else rest
    field = re.search(r"^[ \t]*(?:[-*+][ \t]+)?[*_]*" + name + r":[*_]*[ \t]*(.+)$", section, re.MULTILINE)
    return field.group(1).strip() if field else None


def plan_tasks(entries, plan, held, ledger):
    """Each task of the scope with its Goal:, Depends on: and state, for the progress table the manager shows."""
    text = plan_text(entries, ledger)
    done = {entry["task"] for entry in runs(entries) if entry["agent"] == "dev" and entry["verdict"] in DONE}
    known = {task for tasks in plan.values() for task in tasks}
    found = claims(entries)
    rows = []
    for cycle, tasks in plan.items():
        for task in tasks:
            depends = plan_field(text, task, "Depends on") if text else None
            row = {"task": task, "cycle": cycle, "goal": plan_field(text, task, "Goal") if text else None,
                   "depends": depends}
            needs = {word.rstrip(".") for word in re.split(r"[^\w.]+", depends or "")} & known
            if task in done:
                row["state"] = "done"
            elif task in held:
                row["state"], row["minutes"] = "running", waiting(found[task])
            else:
                row["state"] = "blocked" if needs - done else "todo"
            rows.append(row)
    return rows


def median_task_seconds(entries):
    spent = {}
    for entry in runs(entries):
        if entry["agent"] == "dev" and not is_task(entry, FOLLOW_UP) and entry.get("seconds") is not None:
            spent[entry["task"]] = spent.get(entry["task"], 0) + entry["seconds"]
    done = {entry["task"] for entry in runs(entries) if entry["agent"] == "dev" and entry["verdict"] in DONE}
    measured = [seconds for task, seconds in spent.items() if task in done]
    return statistics.median(measured) if measured else None


def progress(entries, closed, held, ledger):
    plan = plan_cycles(entries)
    if not plan:
        return None
    done = {entry["task"] for entry in runs(entries) if entry["agent"] == "dev" and entry["verdict"] in DONE}
    latest = [entry["task"] for entry in runs(entries) if entry["agent"] == "dev" and not is_task(entry, FOLLOW_UP)]
    names = list(plan)
    current = names[0]
    for task in latest + (list(held) if closed else []):
        current = next((cycle for cycle in names if task in plan[cycle]), current)
    cycles = [{"cycle": cycle, "tasks": tasks, "left": [task for task in tasks if task not in done]}
              for cycle, tasks in plan.items()]
    return {"cycles": cycles, "current": current, "position": names.index(current) + 1, "total": len(names),
            "tasks_left": sum(len(item["left"]) for item in cycles),
            "cycles_left": sum(1 for item in cycles if item["left"] or (item["cycle"] == current and not closed)),
            "tasks": plan_tasks(entries, plan, held, ledger), "median_task_seconds": median_task_seconds(entries)}


def autonomous(entries):
    modes = [entry["mode"] for entry in entries if entry["type"] == "mode"]
    return bool(modes) and modes[-1] == "autonomous"


def until_time(text):
    """--until: HH:MM, the next time this machine's clock shows it, or an ISO time with its offset; never a past one."""
    now = datetime.datetime.now().astimezone()
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    try:
        if clock:
            at = now.replace(hour=int(clock.group(1)), minute=int(clock.group(2)), second=0, microsecond=0)
            at += datetime.timedelta(days=1 if at <= now else 0)
        else:
            at = datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        sys.exit(f"--until takes HH:MM or an ISO time with its offset, not {text!r}")
    if at <= now:
        sys.exit(f"--until {text} is already past")
    return at.isoformat(timespec="seconds")


def mode(args):
    if args.until and args.mode != "autonomous":
        sys.exit("--until is the time the user is back, for autonomous mode only")
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    until = until_time(args.until) if args.until else None
    write(args.ledger, {"type": "mode", "mode": args.mode, **({"until": until} if until else {})})
    print(f"mode {args.mode}" + (f" until {until}" if until else ""))


NIGHT_RUNS = {"dev": "dev", "reviewer": "reviewer", "qa": "qa", "qa_full": "qa --full"}


def night(entries):
    """The time the user is back, while the latest mode entry is autonomous with one: which runs still fit before it."""
    modes = [index for index, entry in enumerate(entries) if entry["type"] == "mode"]
    latest = entries[modes[-1]] if modes else {}
    if latest.get("mode") != "autonomous" or not latest.get("until"):
        return None
    try:
        until = datetime.datetime.fromisoformat(latest["until"])
    except (TypeError, ValueError):
        return None
    left = max(0, int((until - datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
    measured = [entry for entry in runs(entries) if entry.get("seconds") is not None]
    middle = lambda agent: [entry["seconds"] for entry in measured if entry["agent"] == agent and not entry.get("full")]
    full = [entry["seconds"] for entry in measured if entry["agent"] == "qa" and entry.get("full")]
    dev = median_task_seconds(entries)
    expected = {"dev": dev, "reviewer": middle("reviewer"), "qa": middle("qa"), "qa_full": full[-1:]}
    expected = {"dev": None if dev is None else int(dev),
                **{agent: int(statistics.median(values)) if values else None
                   for agent, values in expected.items() if agent != "dev"}}
    fits = {agent: None if value is None else value <= left for agent, value in expected.items()}
    since = [entry for entry in entries[modes[-1] + 1:] if entry["type"] == "run"]
    return {"until": latest["until"], "seconds_left": left, "expected": expected, "fits": fits,
            "over": left == 0 or all(value is False for value in fits.values()),
            "done_since": {"tasks": [entry["task"] for entry in since
                                     if entry["agent"] == "dev" and entry["verdict"] in DONE],
                           "runs": len(since)}}


def span(seconds):
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def night_line(night, paused):
    """status's text line for the night: what fits before the user is back, or, once over, the pause."""
    if night["over"]:
        done = night["done_since"]
        return (f"night over (the user is back at {night['until']}"
                + ("" if not night["seconds_left"] else ", and no run fits before it") + "): "
                + ("the delivery is paused" if paused else
                   "dispatch nothing new; stop what runs and pause as pause.md says, its text the morning summary "
                   f"(done since the time was set: {', '.join(done['tasks']) or 'no task'}, {done['runs']} runs), "
                   "and delete the heartbeat"))
    groups = {True: [], False: [], None: []}
    for agent, label in NIGHT_RUNS.items():
        value = night["expected"][agent]
        groups[night["fits"][agent]].append(label + ("" if value is None else f" ~{span(value)}"))
    return (f"night: until {night['until']} (in {span(night['seconds_left'])})"
            + (f"; fits: {', '.join(groups[True])}" if groups[True] else "")
            + (f"; does not fit (do not dispatch): {', '.join(groups[False])}" if groups[False] else "")
            + (f"; unknown: {', '.join(groups[None])}" if groups[None] else ""))


def deferred(entries):
    items = {}
    for entry in entries:
        if entry["type"] == "defer":
            items[entry["id"]] = {"id": entry["id"], "text": entry["text"], "decision": None, **advice_of(entry)}
        elif entry["type"] == "resolve" and entry["id"] in items:
            items[entry["id"]]["decision"] = entry["decision"]
    return list(items.values())


def defer(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started: run start first")
    item = f"D{len(deferred(entries)) + 1}"
    write(args.ledger, {"type": "defer", "id": item, "text": args.text, "recommend": args.recommend})
    print(f"deferred {item}: needs a final decision before the gate (resolve --id {item})")


def resolve(args):
    entries = read(args.ledger)
    if args.id not in {item["id"] for item in deferred(entries)}:
        sys.exit(f"no deferred item {args.id}")
    write(args.ledger, {"type": "resolve", "id": args.id, "decision": args.decision})
    print(f"{args.id} resolved")


def lesson(args):
    if not read(args.ledger):
        sys.exit("no delivery started: run start first")
    write(args.ledger, {"type": "lesson", "text": args.text, "check": args.check})
    print("lesson recorded" + (f" (automated: {args.check})" if args.check else ""))


def elapsed(cycle):
    """Wall clock from the first run's start to the last one's end; an unmeasured run counts from its timestamp."""
    timed = [entry for entry in cycle if entry.get("at")]
    if not timed:
        return None
    ends = [datetime.datetime.fromisoformat(entry["at"]) for entry in timed]
    starts = [end - datetime.timedelta(seconds=entry.get("seconds") or 0) for end, entry in zip(ends, timed)]
    # A zero span is no measurement (one unmeasured run, or runs stamped in the same second): the cycle has no clock.
    return int((max(ends) - min(starts)).total_seconds()) or None


def classify(entry, found):
    classified = entry.get("origin") or {}
    for name, count in classified.items():
        found[name] += count
    total = sum(entry.get(key, 0) for key in SEVERITIES)
    total += max(entry.get("open", 0) - entry.get("critical", 0) - entry.get("important", 0), 0)
    found["unclassified"] += total - sum(classified.values())


def metrics(entries):
    per_cycle, found = [], {name: 0 for name in ORIGINS + ("unclassified",)}
    for number, cycle in enumerate(cycles(entries), 1):
        passes = [entry for entry in cycle if entry["agent"] in ("reviewer", "qa")]
        counts = {key: sum(entry.get(key, 0) for entry in passes) for key in SEVERITIES + ("open",)}
        for entry in passes:
            classify(entry, found)
        agents = {}
        for entry in cycle:
            if entry.get("seconds") is not None:
                agents[entry["agent"]] = agents.get(entry["agent"], 0) + entry["seconds"]
        fixes = {entry["task"] for entry in cycle if is_task(entry, FIX_TASK)}
        per_cycle.append({"cycle": number, **counts, "fix_rounds": len(fixes), "seconds": sum(agents.values()),
                          "elapsed": elapsed(cycle), "agents": agents,
                          "tokens": sum(entry.get("tokens") or 0 for entry in cycle)})
    loops = {}
    for entry in reviews(entries):
        if entry.get("waived") is not None:
            continue
        loop = loops.setdefault(entry["task"], {"rounds": 0, **{key: 0 for key in SEVERITIES}, "refused": 0, "seconds": 0,
                                                "tokens": 0})
        loop["rounds"] += 1
        loop["refused"] += (entry.get("triage") or {}).get("refused", 0)
        for key in SEVERITIES + ("seconds", "tokens"):
            loop[key] += entry.get(key) or 0
        classify(entry, found)
    measured = [entry for entry in runs(entries) + reviews(entries) if entry.get("waived") is None]
    lessons = [{"text": entry["text"], "check": entry.get("check", "")} for entry in entries
               if entry["type"] == "lesson"]
    return {"cycles": per_cycle, "reviews": loops, "origins": found,
            "time": {**totals(measured, "seconds"), "delivery": delivery_clock(entries, measured)},
            "tokens": totals(measured, "tokens"), "lines": line_totals(entries), "verdicts": verdict_counts(entries),
            "lessons": lessons}


def delivery_clock(entries, measured):
    """The delivery's wall clock, from start to its latest run with the pauses left out, against the time at least one
    agent was running (the union of the measured runs); null before the first measured run."""
    def at(entry):
        return datetime.datetime.fromisoformat(entry["at"])

    spans = sorted((at(entry) - datetime.timedelta(seconds=entry["seconds"]), at(entry)) for entry in measured
                   if entry.get("seconds") and entry.get("at"))
    if not spans or not entries[0].get("at"):
        return None
    begin, end = min(at(entries[0]), spans[0][0]), max(stop for _, stop in spans)
    paused, since = 0, None
    for entry in entries:
        if entry["type"] == "pause" and since is None:
            since = at(entry)
        elif entry["type"] == "resume" and since is not None:
            paused += max((min(at(entry), end) - since).total_seconds(), 0)
            since = None
    paused += max((end - since).total_seconds(), 0) if since else 0
    agents, open_start, open_end = 0, None, None
    for start, stop in spans:
        if open_end is None or start > open_end:
            agents += (open_end - open_start).total_seconds() if open_end else 0
            open_start, open_end = start, stop
        else:
            open_end = max(open_end, stop)
    agents += (open_end - open_start).total_seconds()
    clock = int((end - begin).total_seconds() - paused)
    return {"elapsed": clock, "paused": int(paused), "agents": int(agents),
            "share": round(agents / clock, 2) if clock > 0 else None}


def verdict_counts(entries):
    devs = [entry for entry in runs(entries) if entry["agent"] == "dev"]
    simpler = sum(1 for entry in devs if entry.get("simpler"))
    return {"needs_context": sum(1 for entry in devs if entry["verdict"] == "NEEDS_CONTEXT") - simpler,
            "simpler": simpler, "blocked": sum(1 for entry in devs if entry["verdict"] == "BLOCKED")}


def line_totals(entries):
    tasks, unmeasured = {}, 0
    for entry in runs(entries):
        if entry["agent"] != "dev":
            continue
        size = entry.get("diff")
        if not size:
            unmeasured += 1
            continue
        tasks[entry["task"]] = tasks.get(entry["task"], 0) + size.get("added", 0) + size.get("removed", 0)
    total = sum(tasks.values())
    follow_up = sum(count for task, count in tasks.items() if FOLLOW_UP.fullmatch(task))
    return {"tasks": tasks, "total": total, "follow_up": follow_up,
            "share": round(follow_up / total, 2) if total else None, "unmeasured": unmeasured}


def advice(item):
    return f" (recommend: {item['recommend']})" if item.get("recommend") else ""


def totals(entries, key):
    sums = {"agents": {}, "tasks": {}, "unmeasured": 0}
    for entry in entries:
        if entry.get(key) is None:
            sums["unmeasured"] += 1
            continue
        sums["agents"][entry["agent"]] = sums["agents"].get(entry["agent"], 0) + entry[key]
        if entry["agent"] == "dev":
            sums["tasks"][entry["task"]] = sums["tasks"].get(entry["task"], 0) + entry[key]
    return sums


def status(args):
    entries = read(args.ledger)
    if not entries:
        sys.exit("no delivery started")
    groups = cycles(entries)
    auto = autonomous(entries)
    state, pending = cycle_state(groups[-1], auto, extension(entries, groups[-1]), first(groups))
    closed = not pending
    items = deferred(entries)
    held = in_flight(entries)
    head = git_head(ledger=args.ledger)
    loops, steps = review_state(entries, auto)
    # a task in flight again after a verdict that was not done is no step: its run is pending below
    kept = [(text, step) for text, step in zip(pending, state["steps"]) if step.get("task") not in held]
    pending = loops + [text for text, _ in kept]
    for task, claim in claims(entries).items():
        later = None if closed else later_cycle(entries, groups[-1], task)
        wait = waiting(claim)
        at = f"{claim['at']}{place(claim, ', ')}" + (f", waiting {wait}m" if wait is not None else "")
        since = (f"; the delivery head is now {head[:12]}" if moved(claim, head) else
                 "; the branch head moved since: its work may already be committed, so check its report, add it and "
                 "go on" if committed(claim, head) else "")
        if wait is not None and wait >= PARTIAL_REPORT_MINUTES:
            since += (f"; past {PARTIAL_REPORT_MINUTES} minutes: ask it for a partial report (SendMessage): causes "
                      "found, commits, open hypothesis, and decide with the user whether it goes on")
        pending.append(f"dev {task} dispatched at {at}, for plan cycle {later}: integrate and add it "
                       f"once this cycle closes, or release --task {task}{since}" if later else
                       f"dev {task} dispatched at {at}, no report yet (add it as soon as it reports, or "
                       f"release --task {task}){since}")
    pending += [f"deferred {item['id']} has no decision: {item['text']}" + advice(item)
                for item in items if not item["decision"]]
    steps += [step for _, step in kept] + [{"step": "decide", "id": item["id"], "text": item["text"],
                                            **advice_of(item)} for item in items if not item["decision"]]
    pause_state = paused(entries)
    if pause_state:
        pending.insert(0, f"delivery paused since {pause_state['at']}: {pause_state['text']} "
                          "(resume when work restarts)")
        steps.insert(0, {"step": "resume", **pause_state})
    windows, unreadable = usage_windows(args.ledger)
    usage = usage_advice(windows, usage_settings(usage_files(args.ledger)[1]), usage_margins(entries))
    plans = [entry["plan"] for entry in entries if entry["type"] == "plan"]
    full = [entry for entry in runs(entries) if entry["agent"] == "qa" and entry.get("full")]
    report = {"slug": entries[0].get("slug"), "base": entries[0].get("base"), "ledger": os.path.abspath(args.ledger),
              "plan": plans[-1] if plans else entries[0].get("plan"),
              "cycle": len(groups), "from": cycle_from(entries, groups), "in_flight": list(held), "dispatched": held,
              "claims": [{"task": task, "at": claim["at"], "worktree": claim.get("worktree"),
                          "origin": claim.get("origin"), "tip": tip(claim), "head_moved": moved(claim, head),
                          "waiting_minutes": waiting(claim), "committed": committed(claim, head),
                          "partial_report": (waiting(claim) or 0) >= PARTIAL_REPORT_MINUTES}
                         for task, claim in claims(entries).items()],
              "paused": pause_state, "full_qa": full[-1] if full else None,
              "tasks": {task: entry["verdict"] for task, entry in state["tasks"].items()},
              "reviewer": state["reviewer"], "qa": state["qa"], "runs": groups[-1], "pending": pending,
              "steps": steps, "scope": progress(entries, closed, held, args.ledger),
              "unmeasured": [{"agent": entry["agent"], "task": entry.get("task") or "", "at": entry["at"]}
                             for entry in entries if entry["type"] == "run" and entry.get("seconds") is None
                             and entry.get("waived") is None],
              "autonomous": auto, "deferred": items,
              "notes": [entry["text"] if entry["type"] == "note" else f"paused: {entry['text']}" for entry in entries
                        if entry["type"] == "pause" or (entry["type"] == "note" and not entry.get("validar"))],
              "validar": validar(entries),
              "metrics": metrics(entries), "usage": usage, "night": night(entries), "ready_for_gate": not pending}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"delivery {report['slug']} (base {str(report['base'])[:12]}), cycle {report['cycle']}"
              + (f" from {report['from'][:12]}" if report["from"] else ""))
        if auto:
            print("mode: autonomous (approvals become VALIDAR notes; never merge into or push the default branch)")
        for task, verdict in report["tasks"].items():
            print(f"- {task}: {verdict}")
        for agent in ("reviewer", "qa"):
            if report[agent]:
                print(f"- {agent}: {report[agent][0]['verdict']}")
        if unreadable:
            print("usage: usage.json unreadable")
        if usage and usage["windows"]:
            five, week = usage["windows"].get("five_hour"), usage["windows"].get("seven_day")
            print("usage: " + ", ".join(
                ([f"5h {int(five['percent'])}%"
                  + (f" (resets {reset_at(five).astimezone(datetime.timezone.utc):%H:%M}Z)" if reset_at(five) else "")]
                 if five else []) + ([f"week {int(week['percent'])}%"] if week else [])))
        if usage and usage["economy"]:
            print(f"usage: economy ({usage['economy']}): reviewer on sonnet, one copy at a time")
        if usage and usage["wait"]:
            wait = usage["wait"]
            left = wait["seconds_left"]
            print(f"usage: wait ({wait['window']} at {int(wait['percent'])}%"
                  + (f" + {int(wait['margin'])}% per run" if wait["margin"] else "")
                  + "): dispatch nothing new; pause at the next safe point until "
                  + (f"{wait['resets_at']} (in {left // 3600}h{left % 3600 // 60:02d}m)" if left is not None
                     else "the window resets"))
        if report["night"]:
            print(night_line(report["night"], pause_state))
        for item in pending:
            print(f"pending: {item}")
        for item in report["unmeasured"]:
            task = f" {item['task']}" if item["task"] else ""
            print(f"unmeasured: {item['agent']}{task} at {item['at']}: with its notification, measure --agent "
                  f"{item['agent']}{' --task' + task if task else ''} --at {item['at']} --seconds <duration>")
        for text in report["notes"]:
            print(f"note: {text}")
        for item in report["validar"]:
            print(f"VALIDAR {item['id']}: {item['text']}" + advice(item) if item["decision"] is None
                  else f"validated {item['id']}: {item['text']} -> {item['decision']}")
        for item in items:
            if item["decision"]:
                print(f"deferred {item['id']}: {item['text']} -> {item['decision']}")
        print("ready for gate" if report["ready_for_gate"] else "not ready for gate")
    if args.check and pending:
        sys.exit(1)


NUMBER = r"\d+(?:[.,]\d+)?"
HEAVY_WORDS = {"uma": 1, "um": 1, "one": 1, "duas": 2, "dois": 2, "two": 2, "tres": 3, "three": 3, "quatro": 4,
               "four": 4}


def plain_text(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def gigabytes(text):
    return float(text.replace(",", "."))


def first_number(text, unit=False):
    """The first number inside backticks, else the first number, or the first followed by GB or G."""
    ticked = re.search(r"`[^`\d]*(" + NUMBER + r")[^`]*`", text)
    if ticked:
        return gigabytes(ticked.group(1))
    found = re.search(r"(" + NUMBER + (r")\s*g(?:b)?\b" if unit else ")"), text)
    return gigabytes(found.group(1)) if found else None


def capacity_settings(path):
    """CLAUDE.local.md, Execução em paralelo: the memory and disk peak of a copy, the free-memory floor, the heavy limit."""
    found = {"peak": None, "disk_peak": None, "floor": None, "heavy": None}
    section = []
    inside = False
    labels = {"quanto uma copia ocupa no pico": "peak", "memoria livre minima para despachar": "floor",
              "com o usuario usando a maquina": "heavy"}
    try:
        with open(path, encoding="utf-8") as handle:
            rows = handle.read().splitlines()
    except (OSError, ValueError):
        return found
    for row in rows:
        plain = plain_text(row).lstrip(" -*")
        if row.startswith("#"):
            inside = plain.lstrip("# ").startswith("execucao em paralelo")
        elif inside:
            section.append(plain)
        for label, key in labels.items():
            if not plain.startswith(label) or ":" not in plain:
                continue
            rest = plain.partition(":")[2].strip()
            if rest.startswith("_("):
                continue
            if key == "peak":
                memory, _, disk = rest.partition("disco")
                disk = re.split(r"\.(?:\s|$)|;", disk)[0]
                found["peak"] = first_number(memory, unit=True)
                found["disk_peak"] = (None if re.match(r"[\s:`-]*(?:a\s+)?medir", disk)
                                      else first_number(disk, unit=True)) if disk else None
            elif key == "floor":
                found["floor"] = first_number(rest)
            else:
                found["heavy"] = heavy_count(rest)
    text = " ".join(section)
    if found["floor"] is None:
        more = re.search(r"mais de\s*~?\s*(" + NUMBER + r")\s*g(?:b)?\s+livres?\b", text)
        found["floor"] = gigabytes(more.group(1)) if more else None
    if found["heavy"] is None:
        found["heavy"] = heavy_count(text, copies_only=True)
    if not found["heavy"]:
        found["heavy"] = None
    return found


def heavy_count(text, copies_only=False):
    """The heavy-copy count: a number in backticks, else the first number or word (one to four) before copia(s) pesada(s)
    (copies_only) or copia(s), else the first digit or word."""
    ticked = re.search(r"`\s*(\d+)\s*`", text)
    if ticked and not copies_only:
        return int(ticked.group(1))
    words = "|".join(HEAVY_WORDS)
    before = re.search(r"\b(\d+|" + words + r")\s+copias?" + (r"\s+pesadas?" if copies_only else ""), text)
    if before:
        return int(before.group(1)) if before.group(1).isdigit() else HEAVY_WORDS[before.group(1)]
    if copies_only:
        return None
    digit = re.search(r"\d+", text)
    if digit:
        return int(digit.group(0))
    return next((HEAVY_WORDS[w] for w in re.findall(r"[a-z]+", text) if w in HEAVY_WORDS), None)


def probed(variable, probe):
    """Free GB: the env override when set (empty or invalid means unknown), else the probe; None when unknown."""
    if variable in os.environ:
        try:
            value = float(os.environ[variable].replace(",", "."))
        except ValueError:
            return None
        return value if value >= 0 and value == value and value != float("inf") else None
    try:
        return probe()
    except (OSError, ValueError, AttributeError, ImportError):
        return None


def free_memory_gb():
    if sys.platform == "win32":
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                        ("page_avail", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                        ("virtual_avail", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]

        status = Status()
        status.length = ctypes.sizeof(Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.avail / 1024 ** 3
    if sys.platform.startswith("linux"):
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 ** 2
    return None


def fit(free, peak, reserve):
    """The largest n >= 0 with free - n*peak >= reserve."""
    return max(0, int((free - reserve) / peak + 1e-9)) if peak > 0 else None


def capacity(args):
    entries = read(args.ledger)
    root = os.path.dirname(os.path.dirname(os.path.abspath(args.ledger)))
    memory = probed("PIPELINE_CAPACITY_MEMORY_GB", free_memory_gb)
    disk = probed("PIPELINE_CAPACITY_DISK_GB", lambda: shutil.disk_usage(root).free / 1024 ** 3)
    setting = capacity_settings(os.path.join(root, "CLAUDE.local.md"))
    peak, disk_peak, floor, heavy = setting["peak"], setting["disk_peak"], setting["floor"], setting["heavy"]
    free_mode = autonomous(entries)
    dispatch = None if memory is None or floor is None else memory >= floor
    copies, notes = None, []
    if memory is not None and "PIPELINE_CAPACITY_MEMORY_GB" in os.environ:
        notes.append("memory from PIPELINE_CAPACITY_MEMORY_GB")
    if memory is not None and peak:
        copies = fit(memory, peak, max(peak, floor or 0))
        if disk_peak and disk is not None:
            copies = min(copies, fit(disk, disk_peak, disk_peak))
            notes.append(f"disk {disk:g} GB free, peak {disk_peak:g}"
                         + (", from PIPELINE_CAPACITY_DISK_GB" if "PIPELINE_CAPACITY_DISK_GB" in os.environ else ""))
        if not free_mode and heavy is not None and heavy < copies:
            copies = heavy
            notes.append(f"supervised limit {heavy}")
    if memory is None:
        reason = "free memory unknown: set PIPELINE_CAPACITY_MEMORY_GB"
    elif dispatch is False:
        reason = f"{memory:.1f} GB free, below the floor {floor:g}: do not dispatch"
    elif floor is None:
        reason = 'floor unknown: fill the "Memória livre mínima para despachar" line of CLAUDE.local.md'
    elif not peak:
        reason = "peak unknown: measure the first copy's drop in free memory"
    else:
        shown = "no parallel copy; one dispatch fits" if not copies else f"{copies} parallel cop{'y' if copies == 1 else 'ies'} fit"
        reason = f"{memory:.1f} GB free, floor {floor:g}, peak {peak:g}: {shown}"
    if notes:
        reason += f" ({'; '.join(notes)})"
    report = {"memory_free_gb": memory, "disk_free_gb": disk, "peak_gb": peak, "disk_peak_gb": disk_peak,
              "floor_gb": floor, "heavy_limit": heavy, "autonomous": free_mode, "dispatch": dispatch,
              "copies": copies, "reason": reason}
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        label = {True: "yes", False: "no", None: "unknown"}[dispatch]
        print(f"capacity: dispatch {label}, copies {'unknown' if copies is None else copies}; {reason}")
    if dispatch is False:
        sys.exit(1)


def count(text):
    if not text.isdigit():
        raise argparse.ArgumentTypeError(f"a count is a whole number of 0 or more, not {text!r}")
    return int(text)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", help="default: .superpowers/ledger.jsonl at the root of this worktree, or of "
                                         "the main worktree when this one has none")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start")
    command.add_argument("--slug", required=True)
    command.add_argument("--base", default="HEAD")
    command.add_argument("--plan", help="the approved plan, whose acceptance-criterion ids the gate traces to tests")
    command.add_argument("--archive", action="store_true", help="move an existing delivery aside first")
    command.set_defaults(run=start)
    command = commands.add_parser("add")
    command.add_argument("--agent", required=True, choices=sorted(VERDICTS))
    command.add_argument("--task", default="")
    command.add_argument("--verdict", required=True)
    for severity in SEVERITIES:
        command.add_argument(f"--{severity}", type=count, default=0)
    command.add_argument("--origin", default="", help="design=N,assumption=N,plan=N,execution=N,environment=N")
    command.add_argument("--report", help="the file the manager saved a reviewer or qa report in")
    command.add_argument("--seconds", help="how long the run took, from its completion notification: 90, 12m, 1h5m or 12m30s")
    command.add_argument("--tokens", type=count, help="the tokens the run used, from its completion notification")
    command.add_argument("--full", action="store_true", help="the qa ran the project's full test command")
    command.add_argument("--interface", action="store_true", help="the qa ran the interface (Verificação de interface)")
    command.add_argument("--simpler", action="store_true", help="the dev's NEEDS_CONTEXT is a simpler: proposal")
    command.add_argument("--triage", help="applied=N,refused=N,errata=N: the previous round's findings of a spec or plan review")
    command.set_defaults(run=add)
    for name, run in (("claim", claim), ("release", release)):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True)
        if name == "claim":
            command.add_argument("--worktree", help="where the dev works: an existing directory")
            command.add_argument("--origin", help="the commit the dev's work starts from")
        command.set_defaults(run=run)
    command = commands.add_parser("pause")
    command.add_argument("--text", required=True)
    command.set_defaults(run=pause)
    command = commands.add_parser("resume")
    command.set_defaults(run=resume)
    command = commands.add_parser("note")
    command.add_argument("--text", required=True)
    command.add_argument("--validar", action="store_true", help="the user validates this decision on return")
    command.add_argument("--recommend", help="what you would decide and why, read with the item")
    command.set_defaults(run=note)
    command = commands.add_parser("measure")
    command.add_argument("--agent", required=True, choices=sorted(VERDICTS))
    command.add_argument("--task", default="")
    command.add_argument("--seconds", help="how long the run took, from a notification that arrived after its add")
    command.add_argument("--tokens", type=count, help="the tokens the run used, from that same notification")
    command.add_argument("--at", default="", help="the at of the run it completes, as status --json gives it; needed "
                                                  "only when more than one run of that agent is still unmeasured")
    command.set_defaults(run=measure)
    command = commands.add_parser("validate")
    command.add_argument("--id", required=True)
    command.add_argument("--decision", required=True)
    command.set_defaults(run=validate)
    command = commands.add_parser("waive")
    command.add_argument("--agent", required=True, choices=("reviewer", "qa"))
    command.add_argument("--task", default="", choices=("",) + REVIEWS, help="the spec, plan or security review loop to close")
    command.add_argument("--reason", required=True)
    command.set_defaults(run=waive)
    command = commands.add_parser("extend")
    command.add_argument("--reason", required=True)
    command.add_argument("--task", choices=REVIEWS)
    command.set_defaults(run=extend)
    command = commands.add_parser("plan")
    command.add_argument("--path", required=True)
    command.set_defaults(run=plan)
    command = commands.add_parser("scope")
    command.add_argument("--cycle", required=True, help="the cycle's name in the plan (1, 2, R...)")
    command.add_argument("--tasks", required=True, help="its task ids in plan order, comma-separated; empty removes it")
    command.set_defaults(run=scope)
    command = commands.add_parser("mode")
    command.add_argument("mode", choices=("autonomous", "supervised"))
    command.add_argument("--until", help="the time the user is back: HH:MM or an ISO time with its offset")
    command.set_defaults(run=mode)
    command = commands.add_parser("defer")
    command.add_argument("--text", required=True)
    command.add_argument("--recommend", required=True, help="what you would decide and why, read with the item")
    command.set_defaults(run=defer)
    command = commands.add_parser("resolve")
    command.add_argument("--id", required=True)
    command.add_argument("--decision", required=True)
    command.set_defaults(run=resolve)
    command = commands.add_parser("lesson")
    command.add_argument("--text", required=True)
    command.add_argument("--check", default="")
    command.set_defaults(run=lesson)
    command = commands.add_parser("capacity")
    command.add_argument("--json", action="store_true")
    command.set_defaults(run=capacity)
    command = commands.add_parser("status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--check", action="store_true")
    command.set_defaults(run=status)
    args = parser.parse_args()
    args.ledger = args.ledger or default_ledger(args.command)
    global NEEDS_INTERFACE
    NEEDS_INTERFACE = interface_line(args.ledger)
    args.run(args)


if __name__ == "__main__":
    main()
