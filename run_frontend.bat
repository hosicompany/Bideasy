@echo off
echo [BidEasy] Starting Frontend App...
cd frontend



echo [Setup] Cleaning previous build...
call flutter clean

echo [Setup] Enabling Windows and Web support...
call flutter create . --platforms=windows,web

echo Getting Flutter packages...
call flutter pub get
if %errorlevel% neq 0 (
    echo Flutter execution failed. Please ensure Flutter SDK is installed and added to PATH.
    pause
    exit /b
)
echo Running Flutter App...
echo (If prompted to choose a device, type the number options: 1 for Windows, 2 for Chrome)
call flutter run
pause
