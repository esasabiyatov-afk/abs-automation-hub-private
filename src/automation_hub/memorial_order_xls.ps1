param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$InputPath,
    [switch]$PrintAfterProcessing
)

$ErrorActionPreference = 'Stop'
$resolvedPath = (Resolve-Path -LiteralPath $InputPath).Path
$extension = [System.IO.Path]::GetExtension($resolvedPath).ToLowerInvariant()
if ($extension -notin '.xls', '.xlsx') {
    throw 'Memorial order must be an XLS or XLSX file'
}
$controllerLabel = -join [char[]](0x041A, 0x043E, 0x043D, 0x0442, 0x0440, 0x043E, 0x043B, 0x0435, 0x0440)
$executorLabel = -join [char[]](0x0418, 0x0441, 0x043F, 0x043E, 0x043B, 0x043D, 0x0438, 0x0442, 0x0435, 0x043B, 0x044C)
# One normal-height blank row before each signature, matching the paper form.
$signatureGapHeight = 15.0
$excel = $null
$workbook = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AutomationSecurity = 3 # msoAutomationSecurityForceDisable
    $workbook = $excel.Workbooks.Open($resolvedPath, 0, $false)
    foreach ($sheet in @($workbook.Worksheets)) {
        $used = $sheet.UsedRange
        $firstCell = $sheet.Cells.Item($used.Row, $used.Column)
        $candidate = $used.Find($controllerLabel, $firstCell, -4163, 2, 1, 1, $false, $false, $false)
        $controller = $null
        if ($null -ne $candidate) {
            $firstAddress = $candidate.Address($false, $false)
            do {
                if (([string]$candidate.Text) -match ('^\s*' + [regex]::Escape($controllerLabel) + '\s*:')) {
                    $controller = $candidate
                    break
                }
                $candidate = $used.FindNext($candidate)
            } while ($null -ne $candidate -and $candidate.Address($false, $false) -ne $firstAddress)
        }
        if ($null -eq $controller) {
            throw "Controller label was not found on sheet '$($sheet.Name)'"
        }
        $executor = $null
        $candidate = $used.Find($executorLabel, $firstCell, -4163, 2, 1, 1, $false, $false, $false)
        if ($null -ne $candidate) {
            $firstAddress = $candidate.Address($false, $false)
            do {
                if (([string]$candidate.Text) -match ('^\s*' + [regex]::Escape($executorLabel) + '\s*:')) {
                    $executor = $candidate
                    break
                }
                $candidate = $used.FindNext($candidate)
            } while ($null -ne $candidate -and $candidate.Address($false, $false) -ne $firstAddress)
        }
        if ($null -eq $executor) {
            throw "Executor label was not found on sheet '$($sheet.Name)'"
        }
        $firstRowToClear = $controller.Row + 1
        $lastUsedRow = $used.Row + $used.Rows.Count - 1
        $lastUsedColumn = $used.Column + $used.Columns.Count - 1
        if ($firstRowToClear -le $lastUsedRow) {
            $sheet.Range(
                $sheet.Cells.Item($firstRowToClear, $used.Column),
                $sheet.Cells.Item($lastUsedRow, $lastUsedColumn)
            ).ClearContents() | Out-Null
        }
        $sheet.UsedRange.Rows.AutoFit() | Out-Null
        # Preserve handwriting space: stretch the nearest blank row before
        # "Исполнитель:" and the first blank row before "Контролер:".
        $signatureGapRows = @()
        for ($rowNumber = $executor.Row - 1; $rowNumber -ge $used.Row; $rowNumber--) {
            $rowValues = $sheet.Range($sheet.Cells.Item($rowNumber, $used.Column), $sheet.Cells.Item($rowNumber, $lastUsedColumn)).Value2
            if (-not (@($rowValues) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })) {
                $signatureGapRows += $rowNumber
                break
            }
        }
        for ($rowNumber = $executor.Row + 1; $rowNumber -lt $controller.Row; $rowNumber++) {
            $rowValues = $sheet.Range($sheet.Cells.Item($rowNumber, $used.Column), $sheet.Cells.Item($rowNumber, $lastUsedColumn)).Value2
            if (-not (@($rowValues) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })) {
                $signatureGapRows += $rowNumber
                break
            }
        }
        foreach ($rowNumber in $signatureGapRows) {
            $rowRange = $sheet.Rows.Item($rowNumber)
            if ([double]$rowRange.RowHeight -lt $signatureGapHeight) {
                $rowRange.RowHeight = $signatureGapHeight
            }
        }
        $sheet.Columns.Item(3).ColumnWidth = [double]$sheet.Columns.Item(3).ColumnWidth + 0.75
        $sheet.Columns.Item(6).ColumnWidth = [double]$sheet.Columns.Item(6).ColumnWidth + 0.75
        $sheet.PageSetup.Zoom = $false
        $sheet.PageSetup.FitToPagesWide = 1
        $sheet.PageSetup.FitToPagesTall = $false
    }
    $workbook.Save() | Out-Null
    if ($PrintAfterProcessing) {
        $workbook.PrintOut()
    }
} finally {
    if ($null -ne $workbook) { $workbook.Close($false) }
    if ($null -ne $excel) { $excel.Quit() }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
