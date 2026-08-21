#!/bin/sh
# Lanceur de développement (macOS / Linux). Sous Windows : lancer.bat.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/streamlit ]; then
    exec .venv/bin/streamlit run app.py
fi
exec streamlit run app.py
