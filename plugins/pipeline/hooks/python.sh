#!/bin/sh
# Runs a script of the plugin with Python 3: the first of python (the usual name on Windows) and python3 (often the
# only one on Linux) that is Python 3, so a Python 2 or the Windows store alias is skipped. The hooks of hooks.json
# and the commands of the skills use it. andamento.js tries the same names in the same order, and the native
# pre-commit hook keeps its own copy of this loop: installed in a project, it may meet a plugin root without this
# file.
# Usage: sh python.sh <script> [args...]. Without Python 3 it says so on stderr and exits 1.
for py in python python3; do
  if "$py" -c 'import sys; sys.exit(sys.version_info[0] < 3)' </dev/null >/dev/null 2>&1; then
    exec "$py" "$@"
  fi
done
echo "pipeline: no Python 3 on PATH (tried python, python3); install Python 3." >&2
exit 1
