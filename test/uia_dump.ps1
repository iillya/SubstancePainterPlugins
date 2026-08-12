param([int]$TargetPid)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$outPath = "C:\Users\liuwenbo\AppData\Local\Temp\sp_ui\uia_dump_out.txt"
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetPid)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
$lines = New-Object System.Collections.Generic.List[string]
foreach ($el in $all) {
  try {
    $name = $el.Current.Name
    $type = $el.Current.ControlType.ProgrammaticName
    $cls = $el.Current.ClassName
    $lines.Add(("{0} | {1} | {2}" -f $type, $cls, $name))
  } catch {}
}
[System.IO.File]::WriteAllLines($outPath, $lines, (New-Object System.Text.UTF8Encoding($false)))
