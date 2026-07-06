$in = [Console]::In.ReadToEnd()
try { $j = $in | ConvertFrom-Json } catch { exit 0 }
$f = $null
if ($j.tool_input -and $j.tool_input.file_path) { $f = $j.tool_input.file_path }
elseif ($j.tool_response -and $j.tool_response.filePath) { $f = $j.tool_response.filePath }
if (-not $f) { exit 0 }
$norm = ($f -replace '/', '\')
if (($norm -like 'C:\Project\Bideasy\backend\*') -and ($norm -notlike '*.md')) {
    New-Item -ItemType File -Force -Path (Join-Path $PSScriptRoot '.pending-verify') | Out-Null
}
exit 0
