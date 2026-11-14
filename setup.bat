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

set "CONDA_ENV=%~1"
if not defined CONDA_ENV set "CONDA_ENV=dy"

set "PY="
set "CONDA_BASE="
for /f "delims=" %%i in ('conda info --base 2^>nul') do if not defined CONDA_BASE set "CONDA_BASE=%%i"
if defined CONDA_BASE if exist "%CONDA_BASE%\envs\%CONDA_ENV%\python.exe" set "PY=%CONDA_BASE%\envs\%CONDA_ENV%\python.exe"
if not defined PY if /i "%CONDA_ENV%"=="base" if defined CONDA_BASE if exist "%CONDA_BASE%\python.exe" set "PY=%CONDA_BASE%\python.exe"
if not defined PY goto :no_python

"%PY%" "%~dp0scripts\win_env.py" setup --env "%CONDA_ENV%" %2
exit /b %ERRORLEVEL%

:no_python
echo.
echo [ERROR] conda environment "%CONDA_ENV%" was not found, or conda is not on PATH.
echo         Create it first:
echo             conda create -y -n %CONDA_ENV% python=3.12
echo         Then run setup.bat again. See README.md for details.
echo.
exit /b 1
