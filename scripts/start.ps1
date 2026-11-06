# One-click Windows bootstrap. Tools and dependencies remain inside this project.
param(
    [switch]$Phone,
    [string]$HostAddress,
    [switch]$Check,
    [switch]$NoBrowser,
    [int]$FrontPort = 5175,
    [int]$BackPort = 8002,
    [int]$CaPort = 8765,
    [double]$RuntimeSeconds = 0
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$toolsRoot = Join-Path $projectRoot '.tools'
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "No se pudo completar: $([IO.Path]::GetFileName($File)). Revisa el mensaje anterior y vuelve a ejecutar run.cmd." }
}
function Get-Sha256 {
    param([string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '') }
    finally { $hash.Dispose(); $stream.Dispose() }
}
function Expand-PortableArchive {
    param([string]$Archive, [string]$Destination)
    [Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null
    $prefix = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            if (-not $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta no valida en el archivo portable.' }
            if (-not $entry.Name) { [IO.Directory]::CreateDirectory($target) | Out-Null }
            else {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            }
        }
    } finally { $zip.Dispose() }
}
function Get-VerifiedArchive {
    param([string]$Url, [string]$Checksum, [string]$Destination)
    $archive = Join-Path $toolsRoot ([IO.Path]::GetFileName(([Uri]$Url).AbsolutePath))
    if (-not (Test-Path -LiteralPath $archive) -or (Get-Sha256 $archive) -ne $Checksum) {
        Write-Host 'Descargando herramienta portable...'
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $archive
    }
    if ((Get-Sha256 $archive) -ne $Checksum) { throw 'La descarga no coincide con el SHA-256 oficial.' }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-PortableArchive $archive $Destination
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Este lanzador necesita Windows x64 para MediaPipe.' }
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    $uvPath = if ($uvCommand) { $uvCommand.Source } else { Join-Path $toolsRoot 'uv/uv.exe' }
    if (-not (Test-Path -LiteralPath $uvPath)) {
        Get-VerifiedArchive 'https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip' '0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021' (Join-Path $toolsRoot 'uv')
        $uvPath = (Get-ChildItem -LiteralPath (Join-Path $toolsRoot 'uv') -Filter uv.exe -Recurse | Select-Object -First 1).FullName
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $toolsRoot 'python'
    $env:UV_CACHE_DIR = Join-Path $toolsRoot 'uv-cache'
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $nodePath = if ($nodeCommand) { $nodeCommand.Source } else { '' }
    $usableNode = $false
    if ($nodePath) {
        $nodeVersion = [version]((& $nodePath --version).Trim().TrimStart('v'))
        $usableNode = $nodeVersion -ge [version]'22.12.0'
    }
    if (-not $usableNode) {
        $nodePath = Join-Path $toolsRoot 'node/node-v22.22.2-win-x64/node.exe'
        if (-not (Test-Path -LiteralPath $nodePath)) {
            Get-VerifiedArchive 'https://nodejs.org/dist/v22.22.2/node-v22.22.2-win-x64.zip' '7c93e9d92bf68c07182b471aa187e35ee6cd08ef0f24ab060dfff605fcc1c57c' (Join-Path $toolsRoot 'node')
        }
    }
    $env:PATH = ([IO.Path]::GetDirectoryName($nodePath)) + [IO.Path]::PathSeparator + $env:PATH
    $pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        Write-Host 'Preparando Python 3.12 local...'
        Invoke-Checked $uvPath @('venv','--python','3.12','--managed-python','--seed','.venv')
    }
    & $pythonPath -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'La carpeta .venv usa un Python incompatible. Renombrala y ejecuta run.cmd de nuevo; tus datos estan en data/.' }
    $requirementsHash = Get-Sha256 (Join-Path $projectRoot 'requirements-pose.lock.txt')
    $pythonStamp = Join-Path $projectRoot '.venv/.visionpsy-requirements'
    if (-not (Test-Path -LiteralPath $pythonStamp) -or (Get-Content -LiteralPath $pythonStamp -Raw).Trim() -ne $requirementsHash) {
        Write-Host 'Instalando dependencias de VisionPsy...'
        Invoke-Checked $uvPath @('pip','install','--python',$pythonPath,'-r','requirements-pose.lock.txt')
        [IO.File]::WriteAllText($pythonStamp, $requirementsHash)
    }
    $frontendHash = Get-Sha256 (Join-Path $projectRoot 'frontend/package-lock.json')
    $frontendStamp = Join-Path $projectRoot 'frontend/node_modules/.visionpsy-lock'
    if (-not (Test-Path -LiteralPath $frontendStamp) -or (Get-Content -LiteralPath $frontendStamp -Raw).Trim() -ne $frontendHash) {
        Write-Host 'Preparando interfaz...'
        $npmCli = Join-Path ([IO.Path]::GetDirectoryName($nodePath)) 'node_modules/npm/bin/npm-cli.js'
        Invoke-Checked $nodePath @($npmCli,'--prefix','frontend','ci','--no-audit','--no-fund')
        [IO.File]::WriteAllText($frontendStamp, $frontendHash)
    }
    $launchArguments = @('scripts/setup_local.py','--front-port',"$FrontPort",'--back-port',"$BackPort",'--ca-port',"$CaPort")
    if ($Phone) { $launchArguments += '--phone' }
    if ($HostAddress) { $launchArguments += @('--host',$HostAddress) }
    if ($Check) { $launchArguments += '--check' }
    if ($NoBrowser) { $launchArguments += '--no-browser' }
    if ($RuntimeSeconds -gt 0) { $launchArguments += @('--runtime-seconds',"$RuntimeSeconds") }
    Invoke-Checked $pythonPath $launchArguments
} catch {
    Write-Host "`n$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
