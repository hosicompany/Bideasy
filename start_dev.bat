@echo off
echo Starting BidEasy Project...

:: Start Backend in a new window with error checking
echo Starting Backend...
start "BidEasy Backend" cmd /k "cd backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000 && pause"

:: Start Frontend in a new window
echo Starting Frontend...
cd frontend
start "BidEasy Frontend" cmd /k "flutter run -d chrome"

:: Pause main script
pause
