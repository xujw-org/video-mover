@echo off
rem ===========================================================================
rem Video Mover - Windows update launcher
rem
rem Usage:   update.bat [conda-env-name]    (default env: dy)
rem
rem What it does:
rem   1. git pull --ff-only
rem   2. re-run setup (dependencies, Playwright, upstream patches, ffmpeg)
rem   3. download any missing binary assets
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
if not defined PY goto :no_python

"%PY%" "%~dp0scripts\win_env.py" update --env "%CONDA_ENV%"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Video Mover update exited with code %EXITCODE%
if "%EXITCODE%"=="0" echo Start the GUI with: gui.bat %CONDA_ENV%
exit /b %EXITCODE%

:no_python
echo.
echo [ERROR] No conda environment "%CONDA_ENV%" and no project .venv were found.
echo         Run setup.bat first.
echo.
exit /b 1
