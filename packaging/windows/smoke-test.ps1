param(
    [Parameter(Mandatory = $true)]
    [string]$ReleasePath
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$builder = Join-Path $PSScriptRoot "build_release.py"
$resolvedRelease = (Resolve-Path -LiteralPath $ReleasePath).Path

Push-Location $repositoryRoot
try {
    & python $builder --smoke-only $resolvedRelease
    if ($LASTEXITCODE -ne 0) {
        throw "Windows release smoke test failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
