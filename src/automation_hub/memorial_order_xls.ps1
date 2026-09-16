param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$InputPath,
    [switch]$Print
)

$ErrorActionPreference = 'Stop'
$resolvedPath = (Resolve-Path -LiteralPath $InputPath).Path
$extension = [System.IO.Path]::GetExtension($resolvedPath).ToLowerInvariant()
if ($extension -notin '.xls', '.xlsx') {
    throw 'Memorial order must be an XLS or XLSX file'
}
$excel = $null
$workbook = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AutomationSecurity = 3 # msoAutomationSecurityForceDisable
    # Open read-only. The file returned by ABS must remain byte-for-byte intact.
    $workbook = $excel.Workbooks.Open($resolvedPath, 0, $true)
    if ($Print) {
        $workbook.PrintOut()
    }
} finally {
    if ($null -ne $workbook) { $workbook.Close($false) }
    if ($null -ne $excel) { $excel.Quit() }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
