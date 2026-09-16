$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction Stop

& $python.Source -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name TolubayReports `
    --paths (Join-Path $root 'src') `
    --distpath (Join-Path $root 'release') `
    --workpath (Join-Path $root 'build\\pyinstaller') `
    --specpath (Join-Path $root 'build') `
    --add-data "$root\specs;specs" `
    --add-data "$root\src\automation_hub\memorial_order_xls.ps1;automation_hub" `
    (Join-Path $root 'tolubay_reports_app.py')
