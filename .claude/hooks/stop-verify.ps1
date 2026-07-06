$flag = Join-Path $PSScriptRoot '.pending-verify'
if (-not (Test-Path $flag)) { exit 0 }
$countFile = Join-Path $PSScriptRoot '.verify-failcount'
Set-Location 'C:\Project\Bideasy\backend'
$out = & python -m pytest -x -q 2>&1 | ForEach-Object { $_.ToString() }
if ($LASTEXITCODE -eq 0) {
    Remove-Item $flag, $countFile -Force -ErrorAction SilentlyContinue
    Write-Output '{"systemMessage": "[verify-hook] pytest PASSED - verification gate cleared"}'
    exit 0
}
$n = 1
if (Test-Path $countFile) { try { $n = [int]((Get-Content $countFile -Raw).Trim()) + 1 } catch { $n = 1 } }
Set-Content -Path $countFile -Value $n
if ($n -ge 3) {
    Remove-Item $flag, $countFile -Force -ErrorAction SilentlyContinue
    Write-Output '{"systemMessage": "[verify-hook] pytest FAILED 3 times - ESCALATION: report the failures to the user and do NOT claim completion. Gate released."}'
    exit 0
}
$tail = ($out | Select-Object -Last 30) -join "`n"
[Console]::Error.WriteLine("VERIFICATION GATE: 'cd C:\Project\Bideasy\backend; python -m pytest -x -q' FAILED (attempt $n of 2 before escalation). Fix the failing tests before ending the turn.`n--- output tail ---`n$tail")
exit 2
