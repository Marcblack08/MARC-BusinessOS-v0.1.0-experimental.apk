param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Continue"
$cpuName = "CPU no identificada"
$gpuNames = @()
$ramGb = 0
$osCaption = "Windows"
$logicalProcessors = [Environment]::ProcessorCount

try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name
    if ($cpu) { $cpuName = [string]$cpu }
} catch {}

try {
    $system = Get-CimInstance Win32_ComputerSystem
    if ($system.TotalPhysicalMemory) { $ramGb = [math]::Round(([double]$system.TotalPhysicalMemory / 1GB), 1) }
} catch {}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    if ($os.Caption) { $osCaption = [string]$os.Caption }
} catch {}

try {
    $controllers = @(Get-CimInstance Win32_VideoController)
    $gpuNames = @($controllers | ForEach-Object { [string]$_.Name } | Where-Object { $_ })
} catch {}

$hasNvidia = (@($gpuNames | Where-Object { $_ -match "NVIDIA" }).Count -gt 0)
if ($hasNvidia -and $ramGb -ge 16) {
    $profile = "GPU_CANDIDATE"
    $recommendation = "El PC tiene una GPU NVIDIA y al menos 16 GB de RAM. MARC puede probar flujos visuales compatibles, pero la compatibilidad CUDA depende de la GPU y del modelo."
} else {
    $profile = "CPU_SAFE"
    $recommendation = "Usar montaje FFmpeg y voz local; no descargar automáticamente modelos visuales grandes. La generación neuronal puede ser lenta o no caber en memoria."
}

$report = [ordered]@{
    detected_at = (Get-Date).ToString("o")
    operating_system = $osCaption
    architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    cpu = $cpuName
    logical_processors = $logicalProcessors
    ram_gb = $ramGb
    gpus = $gpuNames
    hardware_profile = $profile
    visual_models_auto_download = $false
    recommendation = $recommendation
}

$parent = Split-Path -Parent $OutputPath
if ($parent -and !(Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host ""
Write-Host "Perfil de equipo: $profile"
Write-Host "CPU: $cpuName"
Write-Host "RAM: $ramGb GB"
Write-Host "GPU: $($gpuNames -join ', ')"
Write-Host "Informe: $OutputPath"
Write-Host $recommendation
