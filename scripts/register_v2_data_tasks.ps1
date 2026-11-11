<#
.SYNOPSIS
    Registra (o quita) las tareas programadas de captura de datos de la v2 (prefijo MinervaV2).

.DESCRIPTION
    Tareas del usuario actual, sin privilegios de administrador, que corren el python del entorno
    virtual del repositorio con `conhost.exe --headless` (no abren ventanas):

      MinervaV2OrderBook      cada 5 min    scripts\record_market_data.py orderbook
      MinervaV2Funding        cada 60 min   scripts\record_market_data.py funding
      MinervaV2FearGreed      diaria 02:10  scripts\record_market_data.py feargreed
      MinervaV2HistoryUpdate  cada 6 h      scripts\update_history_file.py --via-copy

    Los datos van a history\market_v2.db y history\history_v2.db (fuera de git y de data\). No
    tocan la v1: los nombres son de la v2 y se comprueban con Assert-NotV1Resources. Como el resto
    del repositorio, habla con el Programador solo por la puerta `$script:SchtasksExe` de
    docker_common.ps1 (en las pruebas apunta a una trampa).

.PARAMETER Remove
    Quita las cuatro tareas en vez de registrarlas.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_v2_data_tasks.ps1
#>
param([switch]$Remove)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\docker_common.ps1"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

$Tasks = @(
    @{ Name = "MinervaV2OrderBook"; Schedule = @("/SC", "MINUTE", "/MO", "5");
       Command = "scripts\record_market_data.py orderbook" },
    @{ Name = "MinervaV2Funding"; Schedule = @("/SC", "MINUTE", "/MO", "60");
       Command = "scripts\record_market_data.py funding" },
    @{ Name = "MinervaV2FearGreed"; Schedule = @("/SC", "DAILY", "/ST", "02:10");
       Command = "scripts\record_market_data.py feargreed" },
    @{ Name = "MinervaV2HistoryUpdate"; Schedule = @("/SC", "HOURLY", "/MO", "6");
       Command = "scripts\update_history_file.py --via-copy" }
)

foreach ($t in $Tasks) {
    if (-not $t.Name.StartsWith("MinervaV2")) { throw "La tarea $($t.Name) no tiene el prefijo MinervaV2." }
    Assert-NotV1Resources -Task $t.Name
}

if ($Remove) {
    foreach ($t in $Tasks) {
        $result = Invoke-Native $script:SchtasksExe @("/Delete", "/TN", $t.Name, "/F") 30
        if ($result.ExitCode -eq 0) { Write-Output "Quitada: $($t.Name)" }
    }
    return
}

if (-not (Test-Path $Python)) { throw "No existe $Python (crea el entorno virtual del repositorio)." }
if ($RepoRoot -match "\s") { throw "La ruta del repositorio tiene espacios ($RepoRoot): muevelo a una ruta sin espacios." }

foreach ($t in $Tasks) {
    # El directorio de trabajo de una tarea creada asi es System32 y los scripts usan rutas relativas
    # a la raiz del repositorio: se entra a ella con `cmd /c cd /d` antes de correr python.
    $tr = "conhost.exe --headless cmd.exe /c cd /d $RepoRoot && .venv\Scripts\python.exe $($t.Command)"
    $argList = @("/Create", "/TN", $t.Name) + $t.Schedule + @("/TR", $tr, "/F")
    $result = Invoke-Native $script:SchtasksExe $argList 30
    if ($result.ExitCode -ne 0) {
        throw "No se pudo registrar $($t.Name): $(Get-Tail ($result.Stderr + ' ' + $result.Stdout))"
    }
    Write-Output "Registrada: $($t.Name)"
}
