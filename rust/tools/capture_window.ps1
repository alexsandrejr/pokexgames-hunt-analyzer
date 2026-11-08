# Captura a janela do app (mesmo coberta por outras) num PNG, no tamanho pedido.
# Uso: powershell -File rust/tools/capture_window.ps1 -Out captura.png [-Width 1320 -Height 820]
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Width = 1320,
    [int]$Height = 820,
    [string]$Title = "PokeXGames Hunt Analyzer"
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int hgt, uint flags);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$process = Get-Process | Where-Object { $_.MainWindowTitle -eq $Title } | Select-Object -First 1
$handle = if ($process) { $process.MainWindowHandle } else { [IntPtr]::Zero }
if ($handle -eq [IntPtr]::Zero) { Write-Error "Janela '$Title' não encontrada"; exit 1 }
# Tamanho da área da janela (com a borda do Windows), como as capturas do Python.
[void][Win]::SetWindowPos($handle, [IntPtr]::Zero, 40, 40, $Width, $Height, 0x0044)
Start-Sleep -Milliseconds 900
$rect = New-Object Win+RECT
[void][Win]::GetWindowRect($handle, [ref]$rect)
$bitmap = New-Object System.Drawing.Bitmap ($rect.Right - $rect.Left), ($rect.Bottom - $rect.Top)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
[void][Win]::PrintWindow($handle, $hdc, 2)  # PW_RENDERFULLCONTENT: inclui o conteúdo do WebView2
$graphics.ReleaseHdc($hdc)
$bitmap.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose(); $bitmap.Dispose()
Write-Output "salvo: $Out"
