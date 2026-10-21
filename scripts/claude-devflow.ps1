# claude-devflow.ps1 - Windows PowerShell entry point, same behavior as bin/claude-devflow.
#
#   claude-devflow [claude args...]   bootstrap the current folder, start Claude with DevFlow
#                                     (and Ponytail when node is available)
#   claude-devflow launch ...         managed run (scripts/devflow_operations.py launch)
#   claude-devflow office ...         live office view (scripts/devflow_office.py)
#   claude-devflow map [cmd ...]      Graphify code map (scripts/devflow_code_map.py; default: build)
#   claude-devflow doctor             check prerequisites
#
# Use from the PowerShell profile so `git pull` keeps it current:
#   function claude-devflow { & "$env:DEVFLOW_HOME\scripts\claude-devflow.ps1" @args }
#
# Environment: DEVFLOW_HOME (defaults to this file's repo), DEVFLOW_BASH (Git Bash path),
# DEVFLOW_PONYTAIL=0 (skip Ponytail). Proxy variables are left as the caller set them.
# Windows PowerShell 5.1 compatible; keep this file ASCII-only.

$ErrorActionPreference = 'Stop'

$DevflowHome = $env:DEVFLOW_HOME
if (-not $DevflowHome) { $DevflowHome = Split-Path -Parent $PSScriptRoot }
$env:DEVFLOW_HOME = $DevflowHome

$PluginDir = Join-Path $DevflowHome 'dist/devflow-plugin'
$PonytailDir = Join-Path $DevflowHome '.claude/vendor/ponytail'
# Same roles as bin/claude-devflow and devflow_operations.PONYTAIL_ROLES.
$PonytailRoles = 'backend-engineer|frontend-engineer|database-engineer|ai-data-engineer|qa-automation'

function Find-Tool([string[]]$Names) {
    foreach ($name in $Names) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Find-Bash {
    if ($env:DEVFLOW_BASH -and (Test-Path $env:DEVFLOW_BASH)) { return $env:DEVFLOW_BASH }
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Git/bin/bash.exe' }
    if ($env:LOCALAPPDATA) { $candidates += Join-Path $env:LOCALAPPDATA 'Programs/Git/bin/bash.exe' }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    # Not System32\bash.exe: that is WSL, which cannot see Windows paths the same way.
    $bash = Get-Command bash -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'System32' } | Select-Object -First 1
    if ($bash) { return $bash.Source }
    return $null
}

function Fail([string]$Message) {
    [Console]::Error.WriteLine("claude-devflow: $Message")
    exit 1
}

$Python = Find-Tool @('python3', 'python', 'py')
$Here = (Get-Location).Path
$Sub = if ($args.Count -gt 0) { [string]$args[0] } else { '' }
$Rest = @($args | Select-Object -Skip 1)

switch ($Sub) {
    { $_ -in @('-h', '--help', 'help') } {
        Get-Content $PSCommandPath -TotalCount 16 | ForEach-Object { $_ -replace '^# ?', '' }
        "`nDEVFLOW_HOME: $DevflowHome"
        exit 0
    }
    'doctor' {
        "DEVFLOW_HOME: $DevflowHome"
        $status = 0
        $checks = [ordered]@{ git = @('git'); python = @('python3', 'python', 'py'); jq = @('jq'); claude = @('claude') }
        foreach ($key in $checks.Keys) {
            $found = Find-Tool $checks[$key]
            if ($found) { '  [ok]     {0,-8} {1}' -f $key, $found } else { "  [eksik]  $key"; $status = 1 }
        }
        $bash = Find-Bash
        if ($bash) { '  [ok]     {0,-8} {1}' -f 'bash', $bash } else { '  [eksik]  bash (Git Bash; DEVFLOW_BASH ile yolu verin)'; $status = 1 }
        if (Test-Path (Join-Path $PluginDir '.claude-plugin/plugin.json')) { "  [ok]     plugin   $PluginDir" } else { '  [yok]    plugin   ilk calistirmada build edilir' }
        if ($env:DEVFLOW_PONYTAIL -eq '0') { '  [kapali] ponytail DEVFLOW_PONYTAIL=0' }
        elseif (-not (Find-Tool @('node'))) { '  [uyari]  ponytail node yok; ponytail yuklenmeyecek' }
        elseif (Test-Path (Join-Path $PonytailDir '.claude-plugin/plugin.json')) { "  [ok]     ponytail $PonytailDir" }
        else { "  [uyari]  ponytail $PonytailDir bulunamadi" }
        $graphify = Find-Tool @('graphify')
        if ($graphify) { "  [ok]     graphify $(& $graphify --version 2>$null) (opsiyonel kod haritasi)" }
        else { '  [yok]    graphify opsiyonel; kod haritasi icin: uv tool install graphifyy==0.9.93' }
        exit $status
    }
    'office' {
        if (-not $Python) { Fail 'eksik arac: python (claude-devflow doctor)' }
        & $Python (Join-Path $DevflowHome 'scripts/devflow_office.py') --target $Here @Rest
        exit $LASTEXITCODE
    }
    'map' {
        if (-not $Python) { Fail 'eksik arac: python (claude-devflow doctor)' }
        if ($Rest.Count -eq 0) { $Rest = @('build') }
        & $Python (Join-Path $DevflowHome 'scripts/devflow_code_map.py') @Rest
        exit $LASTEXITCODE
    }
    'launch' {
        if (-not $Python) { Fail 'eksik arac: python (claude-devflow doctor)' }
        & $Python (Join-Path $DevflowHome 'scripts/devflow_operations.py') launch --target $Here @Rest
        exit $LASTEXITCODE
    }
}

# Default: rebuild plugin, bootstrap the current folder, start Claude.
if (-not $Python) { Fail 'eksik arac: python (claude-devflow doctor)' }
if (-not (Find-Tool @('claude'))) { Fail 'eksik arac: claude (claude-devflow doctor)' }
$Bash = Find-Bash
if (-not $Bash) { Fail 'Git Bash bulunamadi; DEVFLOW_BASH ile yolu verin (claude-devflow doctor)' }

# Rebuild every time so a git pull never leaves an old plugin behind.
& $Python (Join-Path $DevflowHome 'scripts/build_devflow_plugin.py') | Out-Null
if ($LASTEXITCODE -ne 0) { Fail 'plugin build basarisiz' }

& $Bash "$($DevflowHome -replace '\\', '/')/scripts/devflow_bootstrap.sh" ($Here -replace '\\', '/')
if ($LASTEXITCODE -ne 0) { Fail 'bootstrap basarisiz' }

$PluginArgs = @('--plugin-dir', $PluginDir)
$PonytailManifest = Join-Path $PonytailDir '.claude-plugin/plugin.json'
if ($env:DEVFLOW_PONYTAIL -ne '0' -and (Test-Path $PonytailManifest) -and (Find-Tool @('node'))) {
    # ultra questions the request itself; DevFlow scope is fixed by REQ/AC.
    if ($env:PONYTAIL_DEFAULT_MODE -notin @('lite', 'off')) { $env:PONYTAIL_DEFAULT_MODE = 'full' }
    if (-not $env:PONYTAIL_SUBAGENT_MATCHER) { $env:PONYTAIL_SUBAGENT_MATCHER = $PonytailRoles }
    $PluginArgs += @('--plugin-dir', $PonytailDir)
}

& claude @PluginArgs @args
exit $LASTEXITCODE
