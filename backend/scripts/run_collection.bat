@echo off
REM 나라장터 5년치 데이터 수집 배치 스크립트
REM 사용법: run_collection.bat [옵션]
REM   옵션:
REM     /resume   - 중단된 지점부터 재개
REM     /bg       - 백그라운드 실행

cd /d "%~dp0\.."
set SCRIPT_DIR=%~dp0
set LOG_FILE=%SCRIPT_DIR%..\data\collection_console.log

echo ===================================
echo 나라장터 낙찰 데이터 5년치 수집
echo 시작 시각: %date% %time%
echo ===================================

REM 백그라운드 옵션 확인
if "%1"=="/bg" (
    echo 백그라운드로 실행합니다...
    start /min cmd /c "python scripts\collect_5years_data.py %2 %3 >> %LOG_FILE% 2>&1"
    echo 실행 완료. 로그 확인: %LOG_FILE%
    exit /b
)

REM 일반 실행
python scripts\collect_5years_data.py %*

echo ===================================
echo 완료 시각: %date% %time%
echo ===================================
pause
