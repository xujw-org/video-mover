@echo off
rem ===========================================================================
rem Video Mover - Windows update launcher
rem
rem Usage:   update.bat [conda-env-name]    (default env: dy)
rem
rem What it does:
rem   1. locate an existing conda env / .venv, or install Python if necessary
rem   2. git pull --ff-only
rem   3. re-run setup (dependencies, Playwright, upstream patches, ffmpeg)
rem   4. download any missing binary assets
rem
rem This file is intentionally ASCII-only (see start.bat for the reason).
rem ===========================================================================
setlocal enableextensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "CONDA_ENV=%~1"
if not defined CONDA_ENV set "CONDA_ENV=dy"

set "PY="
set "CONDA_BASE="
for /f "delims=" %%i in ('conda info --base 2^>nul') do if not defined CONDA_BASE set "CONDA_BASE=%%i"
if defined CONDA_BASE if exist "%CONDA_BASE%\envs\%CONDA_ENV%\python.exe" set "PY=%CONDA_BASE%\envs\%CONDA_ENV%\python.exe"
if not defined PY if /i "%CONDA_ENV%"=="base" if defined CONDA_BASE if exist "%CONDA_BASE%\python.exe" set "PY=%CONDA_BASE%\python.exe"
if not defined PY if /i "%CONDA_ENV%"=="dy" if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
rem Fallback: hand over to win_env.py with conda's base python. It resolves envs
rem outside the default envs dir and creates a missing env/.venv, so a machine
rem whose setup used conda base or .venv still updates without extra commands.
if not defined PY if defined CONDA_BASE if exist "%CONDA_BASE%\python.exe" set "PY=%CONDA_BASE%\python.exe"
if defined PY goto have_python

rem No conda env, no .venv, no conda base interpreter: locate or install Python
rem 3.12+ first (winget, then the python.org installer), same as setup.bat.
rem bootstrap_python.ps1 prints "PYTHON=<path>" on stdout.
for /f "usebackq tokens=1,* delims==" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_python.ps1"`) do if /i "%%a"=="PYTHON" set "PY=%%b"
if not defined PY goto :no_python

:have_python
"%PY%" "%~dp0scripts\win_env.py" update --env "%CONDA_ENV%"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Video Mover update exited with code %EXITCODE%
if "%EXITCODE%"=="0" echo Start the GUI with: gui.bat %CONDA_ENV%
exit /b %EXITCODE%

:no_python
echo.
echo [ERROR] No Python 3.12+ was found and the automatic install failed.
echo         Install Python from https://www.python.org/downloads/
echo         (tick "Add python.exe to PATH"), or install Miniconda, then run update.bat again.
echo.
exit /b 1
