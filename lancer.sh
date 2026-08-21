#!/bin/sh
# Lanceur de développement (macOS / Linux). Sous Windows : lancer.bat.
cd "$(dirname "$0")" || exit 1

if [ -x .venv/bin/python ]; then
    exec .venv/bin/python demarrer.py "$@"
fi
exec python3 demarrer.py "$@"
