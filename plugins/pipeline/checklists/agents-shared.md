# Shared by the agents

Read by `dev` and `qa`.

## Dev server
Reuse a dev server already running for this directory; start one only with the Bash tool's background mode, with the UI server command of "Comandos" when the project has one.

## Processes
Before reporting, stop every server and background shell you started, each by its own id: a background shell with `TaskStop`, a process with the PID that listens on the port you started it on (with its children). Never stop a process by program or image name: other copies and the user's own services run the same program. Nothing you started is left running.
