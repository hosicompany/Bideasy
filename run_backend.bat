@echo off
echo [BidEasy] Starting Backend Server...
cd backend
echo Installing dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Python execution failed. Please ensure Python is installed and added to PATH.
    pause
    exit /b
)
echo Starting Uvicorn Server...
python -m uvicorn main:app --reload
pause
