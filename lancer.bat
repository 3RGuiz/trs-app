@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Application TRS - rendement et TRS de la ligne

rem Lanceur Windows. Double-cliquez sur ce fichier pour demarrer l'application.
rem La preparation du poste se fait une seule fois, avec preparer_poste.bat.

set "PYTHON="
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"
if not defined PYTHON if exist "python-embed\python.exe" set "PYTHON=python-embed\python.exe"

if not defined PYTHON (
    echo.
    echo   L'application n'est pas encore installee sur ce poste.
    echo.
    echo   Fermez cette fenetre, puis double-cliquez une seule fois sur :
    echo       preparer_poste.bat
    echo.
    pause
    exit /b 1
)

"%PYTHON%" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   L'installation de l'application est incomplete.
    echo.
    echo   Fermez cette fenetre, puis relancez :
    echo       preparer_poste.bat
    echo.
    pause
    exit /b 1
)

echo.
echo   Demarrage de l'application...
echo   Votre navigateur va s'ouvrir sur la page d'accueil.
echo.
echo   IMPORTANT : laissez cette fenetre ouverte tant que vous utilisez
echo   l'application. Pour quitter, fermez cette fenetre.
echo.

"%PYTHON%" -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo   L'application s'est arretee sur une erreur.
    echo   Le detail est affiche ci-dessus : transmettez-le au responsable
    echo   de l'outil.
    echo.
    pause
)
endlocal
