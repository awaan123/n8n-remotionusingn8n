param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$ffmpeg = Join-Path $ProjectRoot '.remotion-binaries\ffmpeg.exe'
$ffprobe = Join-Path $ProjectRoot '.remotion-binaries\ffprobe.exe'

function Get-VideoDimensions([string]$Path) {
  $probe = & $ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of default=nw=1 $Path
  return @{
    Width = [int](($probe | Where-Object { $_ -like 'width=*' }) -replace '^width=', '')
    Height = [int](($probe | Where-Object { $_ -like 'height=*' }) -replace '^height=', '')
  }
}

$jobs = @()
foreach ($relativeFolder in @('renders\4k', 'renders\local-3840px')) {
  $inputFolder = Join-Path $ProjectRoot $relativeFolder
  $outputFolder = Join-Path $inputFolder '2160px'
  New-Item -ItemType Directory -Force -Path $outputFolder | Out-Null

  Get-ChildItem -LiteralPath $inputFolder -File -Filter '*.mp4' | ForEach-Object {
    $dimensions = Get-VideoDimensions $_.FullName
    if ($dimensions.Width -ne 3840 -or $dimensions.Height -ne 3840) {
      return
    }

    $outputPath = Join-Path $outputFolder $_.Name
    if (Test-Path -LiteralPath $outputPath) {
      $outputDimensions = Get-VideoDimensions $outputPath
      if ($outputDimensions.Width -eq 2160 -and $outputDimensions.Height -eq 2160) {
        Write-Output "skipped-existing,$relativeFolder,$($_.Name)"
        return
      }
      throw "Refusing to replace invalid existing output: $outputPath"
    }

    $jobs += [PSCustomObject]@{ Input = $_.FullName; Output = $outputPath; Folder = $relativeFolder; Name = $_.Name }
  }
}

Write-Output "pending_conversions=$($jobs.Count)"
foreach ($job in $jobs) {
  & $ffmpeg -hide_banner -loglevel error -i $job.Input -map 0:v:0 -vf 'scale=2160:2160:flags=lanczos' -c:v libx264 -preset medium -crf 15 -pix_fmt yuv420p -movflags +faststart -an $job.Output
  if ($LASTEXITCODE -ne 0) {
    throw "Conversion failed: $($job.Input)"
  }

  $dimensions = Get-VideoDimensions $job.Output
  if ($dimensions.Width -ne 2160 -or $dimensions.Height -ne 2160) {
    throw "Output dimension check failed: $($job.Output)"
  }
  Write-Output "converted,$($job.Folder),$($job.Name)"
}

Write-Output 'conversion_complete'
