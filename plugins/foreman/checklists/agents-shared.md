# Shared by the agents

Read by `dev` and `qa`; the `reviewer` reads "Skills".

## Skills
Load with the Skill tool, before the work it covers, a skill the brief, `CLAUDE.md` or `docs/lessons.md` names and any listed one that fits the task. Never one that runs the delivery or sets up where it happens (brainstorming, writing or executing a plan, dispatching agents, creating a worktree, finishing a branch): that is the manager's. Where a skill differs from your agent file, the file wins. A named skill that is not installed blocks nothing: go on without it and say so in the report.

## Commands
When `CLAUDE.local.md` has an "Ambiente dos comandos" line, run every command of "Comandos" after it, joined with `&&`, as the gate does.

## Dev server
Reuse a dev server already running for this directory only when it serves the commit under test and the project resets its state (a restart or a reset) before each run of the suite; otherwise start a new one, and `qa` names in its report the commit the server served. Start one only with the Bash tool's background mode, with the UI server command of "Comandos" when the project has one.

## Processes
Before reporting, stop every server and background shell you started, each by its own id: a background shell with `TaskStop`, a process by its PID, the one that listens on the port you started it on included (with its children). Never stop a process by program or image name: other copies and the user's own services run the same program. Nothing you started is left running: the report names each port you started a server on (`ports:`), and the ledger refuses a `qa` report while one of them still accepts connections, and a `dev` run while anything still runs from its worktree.
