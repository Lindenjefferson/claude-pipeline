# Shared by the agents

Read by `dev` and `qa` (all of it) and by `reviewer` (the knowledge graph).

## Knowledge graph (when present)
If `graphify-out/graph.json` exists, orient with `python -m graphify query "<question>"` (`python3` where `python` is not Python 3) before grepping, then verify in the real files. A hook that asks for `graphify query` means this same command. The graph is a map, not proof.

## Dev server
Reuse a dev server already running for this directory; start one only with the Bash tool's background mode, with the UI server command of "Comandos" when the project has one.

## Processes
Before reporting, stop every server and background shell you started, each by its own id: a background shell with `TaskStop`, a process with the PID that listens on the port you started it on (with its children). Never stop a process by program or image name: other copies and the user's own services run the same program. Nothing you started is left running.
