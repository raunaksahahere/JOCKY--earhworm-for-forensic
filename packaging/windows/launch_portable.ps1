param([Parameter(Mandatory=$true)][string]$Bundle, [Parameter(Mandatory=$true)][string]$Workspace)
$ErrorActionPreference = 'Stop'
if (-not [System.IO.Path]::IsPathRooted($Workspace)) { throw 'Workspace must be absolute' }
$env:JOCKY_WORKSPACE = $Workspace
& (Join-Path $Bundle 'jocky_client.exe')
