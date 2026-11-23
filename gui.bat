@echo off
rem ===========================================================================
rem Video Mover - Windows GUI launcher
rem
rem Usage:   gui.bat [conda-env-name]    (default env: dy)
rem
rem Opens the control panel in your browser. Keep this console window open:
rem closing it stops the pipeline that the GUI started.
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

"%PY%" "%~dp0scripts\win_env.py" gui --env "%CONDA_ENV%"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Video Mover GUI exited with code %EXITCODE%
exit /b %EXITCODE%

:no_python
echo.
echo [ERROR] No conda environment "%CONDA_ENV%" and no project .venv were found.
echo         Run setup.bat first: it creates the environment and installs dependencies.
echo.
exit /b 1
