<#
.SYNOPSIS
  Share local file(s) or a web app through the fileshare service.

.DESCRIPTION
  Prints a clean, login-free public link.

    share.ps1 <file>                  single file  -> https://<host>/s/<token>
    share.ps1 <file.md>               markdown, rendered as a web page
    share.ps1 <file.html>             self-contained page -> renders in browser
    share.ps1 <dir>                   multi-file web app (needs index.html)
    share.ps1 -Web <dir|zip|html>     force "web app" (rendered/served)
    share.ps1 -File <anything>        force single-file download
    share.ps1 -TtlDays <n> <path>     override link lifetime for this upload
    share.ps1 -List                   list live shares (admin)
    share.ps1 -Delete <token>         delete one share (admin)

  Credentials come from a config file, never from the environment:
    1. <this dir>\config.json         (created from config.example.json)
    2. ~\.fileshare\config.json       (survives skill re-installs)
#>
param(
  [switch]$Web,
  [switch]$File,
  [int]$TtlDays,
  [switch]$List,
  [string]$Delete,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Paths
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-FileshareConfig {
  $candidates = @(
    (Join-Path $scriptDir 'config.json'),
    (Join-Path $HOME '.fileshare\config.json')
  )
  foreach ($path in $candidates) {
    if (Test-Path -LiteralPath $path) {
      try {
        return (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json)
      }
      catch {
        throw "cannot parse ${path}: $($_.Exception.Message)"
      }
    }
  }
  throw @"
no fileshare config found. Looked in:
  $($candidates[0])
  $($candidates[1])
Create one:
  Copy-Item '$(Join-Path $scriptDir 'config.example.json')' '$($candidates[0])'
then put your token in it. Never paste the token into chat or commit it.
"@
}

$config = Get-FileshareConfig

$token = $config.token
if ([string]::IsNullOrWhiteSpace($token) -or $token -eq 'REPLACE_WITH_YOUR_FILESHARE_TOKEN') {
  throw 'set "token" in your fileshare config.json (it is still the placeholder).'
}

$hostUrl = $config.host
if ([string]::IsNullOrWhiteSpace($hostUrl) -or $hostUrl -eq 'https://fileshare.example.com') {
  Write-Error "Set `"host`" in $ConfigPath to your own fileshare server."; exit 1
}
$hostUrl = $hostUrl.TrimEnd('/')

$ttl = $null
if ($PSBoundParameters.ContainsKey('TtlDays')) { $ttl = $TtlDays }
elseif ($config.PSObject.Properties.Name -contains 'ttl_days' -and $config.ttl_days) { $ttl = [int]$config.ttl_days }

if ($List) {
  Invoke-RestMethod -Method Get -Uri "$hostUrl/api/list" -Headers @{ 'X-Token' = $token } |
    ConvertTo-Json -Depth 5
  return
}

if ($Delete) {
  Invoke-RestMethod -Method Delete -Uri "$hostUrl/api/share/$Delete" -Headers @{ 'X-Token' = $token } |
    ConvertTo-Json -Depth 5
  return
}

function Invoke-FileshareUpload {
  param(
    [string]$Path,
    [string]$Endpoint,
    [string]$DisplayName
  )

  $uploadUrl = "$hostUrl/$Endpoint`?name=$([Uri]::EscapeDataString($DisplayName))"
  if ($null -ne $ttl) { $uploadUrl += "&ttl=$ttl" }

  $response = Invoke-RestMethod `
    -Method Put `
    -Uri $uploadUrl `
    -Headers @{ 'X-Token' = $token } `
    -InFile $Path `
    -TimeoutSec 1800

  if (-not $response.ok) {
    throw "Upload failed: $($response.error)"
  }

  $mb = [math]::Round(([double]$response.size / 1MB), 1)
  Write-Output $response.url
  Write-Output ("  {0}: {1}  {2} MB  expires {3} ({4}d)" -f $response.kind, $response.name, $mb, $response.expires, $response.ttl_days)
}

if (-not $Paths -or $Paths.Count -eq 0) {
  throw 'usage: powershell -ExecutionPolicy Bypass -File share.ps1 [-Web|-File] [-TtlDays <n>] <file|dir> [more...]'
}

foreach ($inputPath in $Paths) {
  $resolved = Resolve-Path -LiteralPath $inputPath -ErrorAction SilentlyContinue
  if (-not $resolved) {
    Write-Error "skip (no such path): $inputPath"
    continue
  }

  $path = $resolved.Path
  $item = Get-Item -LiteralPath $path
  $mode = if ($Web) { 'web' } elseif ($File) { 'file' } elseif ($item.PSIsContainer -or $item.Extension -in @('.html', '.htm')) { 'web' } else { 'file' }

  if ($mode -eq 'web' -and $item.PSIsContainer) {
    $indexPath = Join-Path $path 'index.html'
    if (-not (Test-Path -LiteralPath $indexPath)) {
      Write-Error "skip (web app dir needs index.html): $path"
      continue
    }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName() + '.zip')
    try {
      Compress-Archive -LiteralPath (Join-Path $path '*') -DestinationPath $tmp -Force
      Invoke-FileshareUpload -Path $tmp -Endpoint 'upload-web' -DisplayName $item.Name
    }
    finally {
      Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
  }
  elseif ($mode -eq 'web') {
    Invoke-FileshareUpload -Path $path -Endpoint 'upload-web' -DisplayName $item.Name
  }
  else {
    Invoke-FileshareUpload -Path $path -Endpoint 'upload' -DisplayName $item.Name
  }
}
