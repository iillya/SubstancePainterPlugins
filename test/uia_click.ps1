param([int]$TargetPid, [string]$ButtonName)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$outPath = "C:\Users\liuwenbo\AppData\Local\Temp\sp_ui\uia_click_out.txt"
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetPid)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
$found = "NOT_FOUND"
foreach ($el in $all) {
  try {
    if ($el.Current.Name -eq $ButtonName) {
      $invoke = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
      if ($invoke) {
        $invoke.Invoke()
        $found = "INVOKED: {0}" -f $el.Current.Name
        break
      }
    }
  } catch {}
}
[System.IO.File]::WriteAllText($outPath, $found, (New-Object System.Text.UTF8Encoding($false)))
