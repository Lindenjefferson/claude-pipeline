# Shared by the agents

Read by `dev` and `qa`.

## Commands
When `CLAUDE.local.md` has an "Ambiente dos comandos" line, run every command of "Comandos" after it, joined with `&&`, as the gate does.

## Dev server
Reuse a dev server already running for this directory only when it serves the commit under test and the project resets its state (a restart or a reset) before each run of the suite; otherwise start a new one, and `qa` names in its report the commit the server served. Start one only with the Bash tool's background mode, with the UI server command of "Comandos" when the project has one.

## Processes
Before reporting, stop every server and background shell you started, each by its own id: a background shell with `TaskStop`, a process with the PID that listens on the port you started it on (with its children). Never stop a process by program or image name: other copies and the user's own services run the same program. Nothing you started is left running: the report names each port you started a server on (`ports:`), and the ledger refuses a `qa` report while one of them still accepts connections.
