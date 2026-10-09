@echo off
rem Starts the BabyCue server. Double-click it, or run "start-server.bat --no-detect" (any flags are passed on).
rem First run only: creates .venv, installs the Python packages and builds the website.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up Python for the first time...
    py -3 -m venv .venv || goto :failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
    echo.
    echo For safe-sleep detection on an NVIDIA GPU, also run:
    echo   .venv\Scripts\python -m pip install -e .[ml]
    echo   .venv\Scripts\python -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu126
    echo.
)

if not exist "web\dist\index.html" (
    echo Building the website...
    pushd web
    call npm install || (popd & goto :failed)
    call npm run build || (popd & goto :failed)
    popd
)

".venv\Scripts\python.exe" -m babycue_server %*
echo.
echo BabyCue server stopped.
pause
exit /b 0

:failed
echo.
echo Setup failed; see the messages above.
pause
exit /b 1
