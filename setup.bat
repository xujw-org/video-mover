@echo off
rem ===========================================================================
rem Video Mover - Windows setup launcher
rem
rem Usage:   setup.bat [conda-env-name]      (default: dy)
rem Example: setup.bat dy
rem
rem This file is intentionally ASCII-only. With "chcp 65001" active, cmd.exe
rem parses UTF-8 .bat files by character offsets and can split a multi-byte
rem line in half, executing a fragment as a command. All Chinese messages are
rem printed by scripts\win_env.py instead (see its docstring for details).
rem ===========================================================================
setlocal enableextensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Parse args: the first non-option is the conda env name, options are forwarded.
set "CONDA_ENV="
set "EXTRA="
:parse_args
if "%~1"=="" goto args_done
set "ARG=%~1"
if "%ARG:~0,2%"=="--" goto collect_option
if not defined CONDA_ENV set "CONDA_ENV=%ARG%"
goto next_arg
:collect_option
set "EXTRA=%EXTRA% %ARG%"
:next_arg
shift
goto parse_args
:args_done
if not defined CONDA_ENV set "CONDA_ENV=dy"

set "PY="
set "CONDA_BASE="
for /f "delims=" %%i in ('conda info --base 2^>nul') do if not defined CONDA_BASE set "CONDA_BASE=%%i"
if defined CONDA_BASE if exist "%CONDA_BASE%\envs\%CONDA_ENV%\python.exe" set "PY=%CONDA_BASE%\envs\%CONDA_ENV%\python.exe"
if not defined PY if /i "%CONDA_ENV%"=="base" if defined CONDA_BASE if exist "%CONDA_BASE%\python.exe" set "PY=%CONDA_BASE%\python.exe"
if not defined PY if /i "%CONDA_ENV%"=="dy" if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
rem Fallback: hand over to win_env.py with conda's base python. It resolves envs that
rem live outside the default envs dir and creates a missing env, so a fresh machine
rem does not need a manual "conda create" first.
if not defined PY if defined CONDA_BASE if exist "%CONDA_BASE%\python.exe" set "PY=%CONDA_BASE%\python.exe"
if defined PY goto have_python

rem No conda env, no .venv, no conda base interpreter: locate or install Python 3.12+
rem first (winget, then the python.org installer). Prints "PYTHON=<path>" on stdout.
for /f "usebackq tokens=1,* delims==" %%a in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_python.ps1"`) do if /i "%%a"=="PYTHON" set "PY=%%b"
if not defined PY goto no_python

:have_python
"%PY%" "%~dp0scripts\win_env.py" setup --env "%CONDA_ENV%"%EXTRA%
exit /b %ERRORLEVEL%

:no_python
echo.
echo [ERROR] No Python 3.12+ was found and the automatic install failed.
echo         Install Python from https://www.python.org/downloads/
echo         (tick "Add python.exe to PATH"), or install Miniconda, then run setup.bat again.
echo.
exit /b 1
