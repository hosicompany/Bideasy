# 나라장터 5년치 데이터 수집 PowerShell 스크립트
# 사용법:
#   .\run_collection.ps1                  # 일반 실행
#   .\run_collection.ps1 -Background      # 백그라운드 실행
#   .\run_collection.ps1 -Resume          # 중단 지점부터 재개
#   .\run_collection.ps1 -Resume -Background

param(
    [switch]$Background,
    [switch]$Resume,
    [string]$Type,  # goods, service, construction
    [int]$Months = 60
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
$DataDir = Join-Path $BackendDir "data"
$LogFile = Join-Path $DataDir "collection_console.log"

# data 디렉토리 생성
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

# Python 명령어 구성
$PythonArgs = @("scripts\collect_5years_data.py")
if ($Resume) { $PythonArgs += "--resume" }
if ($Type) { $PythonArgs += "--type"; $PythonArgs += $Type }
if ($Months -ne 60) { $PythonArgs += "--months"; $PythonArgs += $Months }

Write-Host "====================================="
Write-Host "나라장터 낙찰 데이터 수집"
Write-Host "시작: $(Get-Date)"
Write-Host "옵션: $($PythonArgs -join ' ')"
Write-Host "====================================="

Set-Location $BackendDir

if ($Background) {
    Write-Host "백그라운드로 실행합니다..."
    Write-Host "로그 파일: $LogFile"
    
    $Job = Start-Process -FilePath "python" `
        -ArgumentList $PythonArgs `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError "$LogFile.error" `
        -PassThru
    
    Write-Host "프로세스 ID: $($Job.Id)"
    Write-Host ""
    Write-Host "진행 상황 확인:"
    Write-Host "  Get-Content '$LogFile' -Tail 20 -Wait"
    Write-Host ""
    Write-Host "프로세스 종료:"
    Write-Host "  Stop-Process -Id $($Job.Id)"
} else {
    # 포그라운드 실행
    & python $PythonArgs
}

Write-Host "====================================="
Write-Host "완료: $(Get-Date)"
Write-Host "====================================="
