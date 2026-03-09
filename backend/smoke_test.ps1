# Smoke test for backend core endpoints (PowerShell)
$BASE_URL = "http://127.0.0.1:8001"
if ($env:SMOKE_BASE_URL) { $BASE_URL = $env:SMOKE_BASE_URL }

$passCount = 0
$failCount = 0

function Write-Section($name, $url) {
    Write-Host "" 
    Write-Host "== $name =="
    Write-Host "URL: $url"
}

function Mark-Result($ok, $errMsg = "") {
    if ($ok) {
        $script:passCount++
        Write-Host "Result: PASS" -ForegroundColor Green
    } else {
        $script:failCount++
        Write-Host "Result: FAIL" -ForegroundColor Red
        if ($errMsg) { Write-Host "Error: $errMsg" -ForegroundColor Yellow }
    }
}

function Test-Get($name, $path) {
    $url = "$BASE_URL$path"
    Write-Section $name $url
    try {
        $resp = Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 20
        Mark-Result $true
    } catch {
        Mark-Result $false $_.Exception.Message
    }
}

function Invoke-SSEPost($url, $bodyJson) {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(60)

    $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, $url)
    $request.Content = New-Object System.Net.Http.StringContent($bodyJson, [System.Text.Encoding]::UTF8, "application/json")

    $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseContentRead).GetAwaiter().GetResult()
    $status = [int]$response.StatusCode
    $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()

    return @{ Status = $status; Content = $content }
}

function Test-SSEPost($name, $path, $bodyObj, $mustContain) {
    $url = "$BASE_URL$path"
    Write-Section $name $url
    try {
        $json = $bodyObj | ConvertTo-Json -Depth 6 -Compress
        $result = Invoke-SSEPost $url $json
        if ($result.Status -ne 200) {
            Mark-Result $false "HTTP $($result.Status)"
            return
        }
        $content = $result.Content
        $missing = @()
        foreach ($token in $mustContain) {
            if ($content -notmatch [Regex]::Escape($token)) {
                $missing += $token
            }
        }
        if ($missing.Count -gt 0) {
            Mark-Result $false ("Missing tokens: " + ($missing -join ", "))
        } else {
            Mark-Result $true
        }
    } catch {
        Mark-Result $false $_.Exception.Message
    }
}

Write-Host "Backend smoke test starting..." -ForegroundColor Cyan
Write-Host "BASE_URL = $BASE_URL" -ForegroundColor Cyan

# GET /health
Test-Get "GET /health" "/health"

# GET /sessions
Test-Get "GET /sessions" "/sessions"

# POST /tts/full
$ttsBody = @{ text = "你好，我是一个测试语音。" }
$urlTts = "$BASE_URL/tts/full"
Write-Section "POST /tts/full" $urlTts
try {
    $resp = Invoke-RestMethod -Method Post -Uri $urlTts -ContentType "application/json" -Body ($ttsBody | ConvertTo-Json -Compress) -TimeoutSec 60
    if ($null -eq $resp.audioUrl -or $resp.audioUrl -eq "") {
        Mark-Result $false "audioUrl missing"
    } else {
        Mark-Result $true
    }
} catch {
    Mark-Result $false $_.Exception.Message
}

# POST /chat/text/stream (SSE)
Test-SSEPost "POST /chat/text/stream" "/chat/text/stream" @{ text = "你好"; sessionId = $null } @("\"type\":\"start\"", "\"type\":\"done\"")

# POST /chat/text/stream-tts (SSE)
Test-SSEPost "POST /chat/text/stream-tts" "/chat/text/stream-tts" @{ text = "你好"; sessionId = $null } @("\"type\":\"start\"", "\"type\":\"audio_segment\"", "\"type\":\"audio_done\"", "\"type\":\"done\"")

# GET /audio-registry
Test-Get "GET /audio-registry" "/audio-registry"

Write-Host "" 
Write-Host "Smoke test complete. PASS=$passCount FAIL=$failCount" -ForegroundColor Cyan
if ($failCount -gt 0) { exit 1 }
