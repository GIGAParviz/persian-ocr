param([int]$Port = 8000, [string]$ApiKey = "")
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; docker logs --tail 40 persian-ocr-check 2>&1 | Out-Host; docker rm -f persian-ocr-check | Out-Null; exit 1 }

if (-not (docker image inspect persian-ocr:0.2.0 2>$null)) { docker load -i persian-ocr-0.2.0.tar }
docker rm -f persian-ocr-check 2>$null | Out-Null
docker run -d --name persian-ocr-check -p "${Port}:8000" -e "PERSIAN_OCR_API_KEY=$ApiKey" persian-ocr:0.2.0 | Out-Null

$deadline = (Get-Date).AddSeconds(240)
do {
    Start-Sleep -Seconds 5
    $state = docker inspect -f "{{.State.Status}} {{.State.Health.Status}}" persian-ocr-check
    Write-Host "container: $state"
    if ($state -like "exited*") { Fail "container exited" }
} until ($state -eq "running healthy" -or (Get-Date) -gt $deadline)
if ($state -ne "running healthy") { Fail "not healthy after 240 s" }

$base = "http://127.0.0.1:$Port"
$code = curl.exe -s -o NUL -w "%{http_code}" "$base/app"
if ($code -ne "200") { Fail "/app returned $code" }
$json = curl.exe -s -H "X-API-Key: $ApiKey" -F "file=@test-invoice.png" "$base/ocr/text?lexicon=false" | ConvertFrom-Json
if (-not $json.text -or $json.text.Length -lt 200) { Fail "/ocr/text returned no text" }
Write-Host ("OK: healthy, /app 200, /ocr/text {0} characters in {1} s" -f $json.text.Length, $json.time_sec) -ForegroundColor Green
docker rm -f persian-ocr-check | Out-Null
