# Powered by HentaiP feat. ClawMoew.
$ErrorActionPreference = "Stop"
try {
    $script = Join-Path $PSScriptRoot "kars.py"
    if ($env:KARS_PYTHON) {
        & $env:KARS_PYTHON $script @args
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python $script @args
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 $script @args
    } else {
        throw "Python 3.10+ is required. Install it and the requirements first."
    }
    # Native program failures do not throw in Windows PowerShell 5.1.
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
    exit $code
} catch {
    Write-Error $_
    exit 1
}
