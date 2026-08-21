@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Application TRS

rem Lanceur Windows. Double-cliquez sur ce fichier pour demarrer l'application.
rem La preparation du poste se fait une seule fois, avec preparer_poste.bat.

set "PYTHON="
set "PYTHONW="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "PYTHONW=.venv\Scripts\pythonw.exe"
)
if not defined PYTHON if exist "python-embed\python.exe" (
    set "PYTHON=python-embed\python.exe"
    set "PYTHONW=python-embed\pythonw.exe"
)

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

rem Verification par simple presence du dossier : importer Streamlit ici
rem couterait plusieurs secondes au demarrage, pour rien.
set "COMPOSANTS="
if exist ".venv\Lib\site-packages\streamlit" set "COMPOSANTS=1"
if exist "python-embed\Lib\site-packages\streamlit" set "COMPOSANTS=1"

if not defined COMPOSANTS (
    echo.
    echo   L'installation de l'application est incomplete.
    echo.
    echo   Fermez cette fenetre, puis relancez :
    echo       preparer_poste.bat
    echo.
    pause
    exit /b 1
)

rem pythonw.exe : la fenetre de demarrage suffit, pas de console noire.
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" demarrer.py
    exit /b 0
)

rem Sans pythonw, on garde la console et on affiche l'avancement dedans.
echo.
echo   Demarrage de l'application...
echo   La toute premiere ouverture demande quelques secondes de plus
echo   que les suivantes : c'est normal.
echo.
echo   IMPORTANT : laissez cette fenetre ouverte tant que vous utilisez
echo   l'application. Pour quitter, fermez cette fenetre.
echo.

"%PYTHON%" demarrer.py --console

if errorlevel 1 (
    echo.
    echo   L'application s'est arretee sur une erreur.
    echo   Le detail est affiche ci-dessus : transmettez-le au responsable
    echo   de l'outil.
    echo.
    pause
)
endlocal
