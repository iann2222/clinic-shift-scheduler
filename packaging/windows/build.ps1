$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$builder = Join-Path $PSScriptRoot "build_release.py"

Push-Location $repositoryRoot
try {
    & python $builder
    if ($LASTEXITCODE -ne 0) {
        throw "Windows release build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
