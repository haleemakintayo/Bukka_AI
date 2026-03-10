param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$TelegramSecret = "i5N7Oq8Pz74pUPPD_9h4-E9oh0jUbN5UUOUQlSRNDNM",
    [string]$WhatsAppAppSecret = "replace_this_with_meta_app_secret",
    [string]$VendorTelegramChatId = "7490888563",
    [string]$CustomerTelegramChatId = "9988776655",
    [string]$CustomerWhatsAppId = "2348012345678",
    [switch]$SkipTelegram,
    [switch]$SkipWhatsApp,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:results = @()

function Add-Result {
    param(
        [string]$Name,
        [bool]$Pass,
        [string]$Detail
    )

    $script:results += [pscustomobject]@{
        name   = $Name
        passed = $Pass
        detail = $Detail
    }
}

function Get-ErrorDetail {
    param([object]$ErrorRecord)
    try {
        if ($null -ne $ErrorRecord.Exception.Response) {
            $resp = $ErrorRecord.Exception.Response
            $statusCode = [int]$resp.StatusCode
            $statusText = [string]$resp.StatusDescription
            return "HTTP $statusCode $statusText"
        }
    } catch {
        # no-op
    }
    return [string]$ErrorRecord.Exception.Message
}

function Invoke-TestRequest {
    param(
        [string]$Name,
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers,
        [string]$Body,
        [string]$ExpectedStatusValue
    )

    if ($DryRun) {
        Write-Host ("[DRY RUN] {0} {1}" -f $Method, $Uri) -ForegroundColor Yellow
        Add-Result -Name $Name -Pass $true -Detail "Dry-run only"
        return $null
    }

    try {
        if ($Method -eq "GET") {
            $response = Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers
        } else {
            $response = Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -Body $Body -ContentType "application/json"
        }

        $ok = $true
        $detail = "Request succeeded"
        if ($ExpectedStatusValue) {
            $status = [string]$response.status
            $ok = $status -eq $ExpectedStatusValue
            $detail = "status=$status expected=$ExpectedStatusValue"
        }

        Add-Result -Name $Name -Pass $ok -Detail $detail
        return $response
    } catch {
        Add-Result -Name $Name -Pass $false -Detail (Get-ErrorDetail -ErrorRecord $_)
        return $null
    }
}

function New-WhatsAppSignature {
    param(
        [string]$Secret,
        [string]$PayloadJson
    )

    $hmac = New-Object System.Security.Cryptography.HMACSHA256
    try {
        $hmac.Key = [System.Text.Encoding]::UTF8.GetBytes($Secret)
        $hashBytes = $hmac.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($PayloadJson))
    } finally {
        $hmac.Dispose()
    }
    $hex = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
    return "sha256=$hex"
}

function Build-TelegramPayload {
    param(
        [int64]$UpdateId,
        [string]$ChatId,
        [string]$FirstName,
        [string]$Text,
        [int]$MessageId
    )
    $unixTs = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    return @{
        update_id = $UpdateId
        message   = @{
            message_id = $MessageId
            date       = [int]$unixTs
            chat       = @{ id = $ChatId }
            from       = @{ first_name = $FirstName }
            text       = $Text
        }
    } | ConvertTo-Json -Depth 8 -Compress
}

function Build-WhatsAppPayload {
    param(
        [string]$MessageId,
        [string]$FromWaId,
        [string]$Name,
        [string]$Text
    )
    $unixTs = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString()
    return @{
        object = "whatsapp_business_account"
        entry  = @(
            @{
                id      = "local-test-entry"
                changes = @(
                    @{
                        field = "messages"
                        value = @{
                            messaging_product = "whatsapp"
                            metadata          = @{
                                display_phone_number = "1234"
                                phone_number_id      = "1234"
                            }
                            contacts          = @(
                                @{
                                    profile = @{ name = $Name }
                                    wa_id   = $FromWaId
                                }
                            )
                            messages          = @(
                                @{
                                    from      = $FromWaId
                                    id        = $MessageId
                                    timestamp = $unixTs
                                    text      = @{ body = $Text }
                                    type      = "text"
                                }
                            )
                        }
                    }
                )
            }
        )
    } | ConvertTo-Json -Depth 20 -Compress
}

Write-Host "Local webhook tests started..." -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"
if (-not $DryRun) {
    Write-Host "Ensure your API is running: uvicorn main:app --reload"
    Write-Host "Tip: keep TELEGRAM_BOT_TOKEN and META_API_TOKEN empty locally to avoid outbound sends."
}

# Root health check
Invoke-TestRequest -Name "Health root" -Method "GET" -Uri "$BaseUrl/" -Headers @{} -Body "" -ExpectedStatusValue ""

if (-not $SkipTelegram) {
    $telegramHeaders = @{
        "x-telegram-bot-api-secret-token" = $TelegramSecret
    }

    $tUpdate1 = 910001
    $tBody1 = Build-TelegramPayload -UpdateId $tUpdate1 -ChatId $VendorTelegramChatId -FirstName "VendorLocal" -Text "/menu" -MessageId 1001
    Invoke-TestRequest -Name "Telegram vendor command /menu" -Method "POST" -Uri "$BaseUrl/telegram/webhook" -Headers $telegramHeaders -Body $tBody1 -ExpectedStatusValue "ok"

    # duplicate check
    Invoke-TestRequest -Name "Telegram duplicate update ignored" -Method "POST" -Uri "$BaseUrl/telegram/webhook" -Headers $telegramHeaders -Body $tBody1 -ExpectedStatusValue "duplicate_ignored"

    $tUpdate2 = 910002
    $tBody2 = Build-TelegramPayload -UpdateId $tUpdate2 -ChatId $CustomerTelegramChatId -FirstName "CustomerLocal" -Text "how much jollof rice" -MessageId 1002
    Invoke-TestRequest -Name "Telegram customer inquiry" -Method "POST" -Uri "$BaseUrl/telegram/webhook" -Headers $telegramHeaders -Body $tBody2 -ExpectedStatusValue "ok"
}

if (-not $SkipWhatsApp) {
    $wMsgId = "wamid.local.1001"
    $wBody1 = Build-WhatsAppPayload -MessageId $wMsgId -FromWaId $CustomerWhatsAppId -Name "CustomerLocal" -Text "how much jollof rice"
    $wSig1 = New-WhatsAppSignature -Secret $WhatsAppAppSecret -PayloadJson $wBody1
    $wHeaders1 = @{
        "x-hub-signature-256" = $wSig1
    }
    Invoke-TestRequest -Name "WhatsApp customer inquiry" -Method "POST" -Uri "$BaseUrl/webhook" -Headers $wHeaders1 -Body $wBody1 -ExpectedStatusValue "received"

    # duplicate check (same message id)
    Invoke-TestRequest -Name "WhatsApp duplicate message ignored" -Method "POST" -Uri "$BaseUrl/webhook" -Headers $wHeaders1 -Body $wBody1 -ExpectedStatusValue "duplicate_ignored"
}

Write-Host ""
Write-Host "========== Test Summary ==========" -ForegroundColor Cyan
$passed = @($script:results | Where-Object { $_.passed }).Count
$failed = @($script:results | Where-Object { -not $_.passed }).Count
foreach ($r in $script:results) {
    if ($r.passed) {
        Write-Host ("PASS - {0}: {1}" -f $r.name, $r.detail) -ForegroundColor Green
    } else {
        Write-Host ("FAIL - {0}: {1}" -f $r.name, $r.detail) -ForegroundColor Red
    }
}
Write-Host ("Totals => Passed: {0}, Failed: {1}" -f $passed, $failed)

if ($failed -gt 0) {
    exit 1
}
exit 0
