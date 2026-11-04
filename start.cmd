@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
python --version >nul 2>&1
if not errorlevel 1 goto use_python
py -3 --version >nul 2>&1
if not errorlevel 1 goto use_py
set "RELAYLENS_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%RELAYLENS_PYTHON%" goto use_bundled
echo Python 3.10 or newer is required. Install Python, then reopen this launcher.
goto done
:use_python
python run_relaylens.py --interactive %*
goto done
:use_py
py -3 run_relaylens.py --interactive %*
goto done
:use_bundled
"%RELAYLENS_PYTHON%" run_relaylens.py --interactive %*
:done
echo.
pause
