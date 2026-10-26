@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if not errorlevel 1 goto use_python
where py >nul 2>&1
if not errorlevel 1 goto use_py
echo Python 3.10 or newer is required.
goto done
:use_python
python run_relaylens.py --interactive %*
if errorlevel 1 echo RelayLens exited with an error.
goto done
:use_py
py -3 run_relaylens.py --interactive %*
if errorlevel 1 echo RelayLens exited with an error.
:done
echo.
pause
