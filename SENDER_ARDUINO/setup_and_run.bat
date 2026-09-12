@echo off
REM ActuLock -- one-click setup and run (Windows, plain Python -- not MSYS2)
REM Double-click this file. If Windows blocks it, right-click -> Run anyway.

cd /d "%~dp0"

echo Removing old (broken/empty) venv...
if exist venv rmdir /s /q venv

echo Creating a fresh venv with the standard Windows Python launcher...
py -3 -m venv venv
if errorlevel 1 (
    echo.
    echo FAILED: the "py" launcher was not found.
    echo Install Python from https://www.python.org/downloads/ and make sure
    echo you check "Add python.exe to PATH" during install. Then run this
    echo file again.
    pause
    exit /b 1
)

echo Installing dependencies into the venv...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo Starting the backend server...
echo Once it says "Running on http://...", open http://localhost:5000/homepage.html in your browser.
echo.
venv\Scripts\python.exe backend_server.py

pause
