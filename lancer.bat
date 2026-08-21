@echo off
rem Lanceur Windows - double-clic pour demarrer l application.
cd /d "%~dp0"
streamlit run app.py --server.headless=false
pause
