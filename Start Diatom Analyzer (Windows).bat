@echo off
rem Double-click this file to start the Diatom Analyzer.
rem The first start sets everything up (a few minutes, needs internet once); later starts are quick.
title Diatom Analyzer
cd /d "%~dp0"
echo ==================================================
echo   Diatom Analyzer
echo   Keep this window open while you use the tool.
echo   To quit: close the browser tab, then this window.
echo ==================================================
echo.

set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo First start: setting things up. This takes a few minutes and needs internet once...
  %PY% -m venv .venv
  if errorlevel 1 goto :failed
)

set "REQUIREMENTS_ID="
for /f "skip=1 delims=" %%h in ('certutil -hashfile requirements.txt SHA1') do if not defined REQUIREMENTS_ID set "REQUIREMENTS_ID=%%h"
set "INSTALLED_ID="
if exist ".venv\installed.txt" set /p INSTALLED_ID=<".venv\installed.txt"
if not "%REQUIREMENTS_ID%"=="%INSTALLED_ID%" (
  echo Installing the analysis tools...
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto :failed
  > ".venv\installed.txt" echo %REQUIREMENTS_ID%
)

rem Streamlit asks for an email address on its very first run, which would stall here unseen.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo Opening the Diatom Analyzer in your browser...
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
goto :eof

:nopython
echo Python 3.10 or newer is needed - a one-time install.
echo The download page will open now. When installing, tick "Add python.exe to PATH".
echo Then double-click Start Diatom Analyzer again.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:failed
echo.
echo Setup did not finish. Check the internet connection, then double-click this file again.
pause
exit /b 1
