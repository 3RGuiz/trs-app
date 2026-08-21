@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Preparation du poste - Application TRS

echo.
echo   ================================================================
echo    Preparation du poste pour l'application TRS
echo    A faire une seule fois. Comptez quelques minutes.
echo   ================================================================
echo.

rem --- 1. Trouver un Python utilisable -----------------------------------
set "PYTHON_BASE="
where py >nul 2>nul && set "PYTHON_BASE=py -3"
if not defined PYTHON_BASE (
    where python >nul 2>nul && set "PYTHON_BASE=python"
)

if not defined PYTHON_BASE (
    echo   Aucun Python n'est installe sur ce poste.
    echo.
    echo   Demandez au service informatique d'installer Python 3.11 ou
    echo   plus recent, en cochant "Add Python to PATH" a l'installation.
    echo   Source officielle : https://www.python.org/downloads/windows/
    echo.
    pause
    exit /b 1
)

echo   Python detecte : %PYTHON_BASE%
%PYTHON_BASE% --version
echo.

rem --- 2. Creer l'environnement de l'application -------------------------
if exist ".venv\Scripts\python.exe" (
    echo   Environnement deja present, il est reutilise.
) else (
    echo   Creation de l'environnement de l'application...
    %PYTHON_BASE% -m venv .venv
    if errorlevel 1 (
        echo.
        echo   La creation de l'environnement a echoue.
        echo   Verifiez que vous avez le droit d'ecrire dans ce dossier.
        echo.
        pause
        exit /b 1
    )
)

set "PYTHON=.venv\Scripts\python.exe"

rem --- 3. Installer les composants ---------------------------------------
echo.
if exist "paquets\*.whl" (
    echo   Installation depuis le dossier local "paquets" ^(sans internet^)...
    "%PYTHON%" -m pip install --no-index --find-links paquets -r requirements.txt
) else (
    echo   Installation depuis internet...
    "%PYTHON%" -m pip install --upgrade pip
    "%PYTHON%" -m pip install -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo   L'installation des composants a echoue.
    echo.
    echo   Si ce poste n'a pas acces a internet, demandez le dossier
    echo   "paquets" a la personne qui vous a fourni l'application,
    echo   placez-le ici, puis relancez ce script.
    echo.
    pause
    exit /b 1
)

rem --- 4. Verification ----------------------------------------------------
echo.
echo   Verification de l'installation...
"%PYTHON%" -c "import streamlit, pandas, plotly; print('   Composants OK')"
if errorlevel 1 (
    echo   La verification a echoue. Relancez ce script.
    pause
    exit /b 1
)

if not exist "data" mkdir data

echo.
echo   ================================================================
echo    Installation terminee.
echo.
echo    Pour demarrer l'application : double-cliquez sur lancer.bat
echo   ================================================================
echo.
pause
endlocal
