# DEMON — отдалечена инсталация (план Б без .exe)
# Клиентът: Windows+R → powershell → Enter → поставя тази команда:
#   irm https://martin4o123.github.io/demon-centar/install.ps1 | iex
$ErrorActionPreference = "Stop"
$base = "https://martin4o123.github.io/demon-centar/swing_live"
$installDir = Join-Path $env:LOCALAPPDATA "DemonCenter"
$log = Join-Path $env:TEMP "DEMON-install.log"

function W($t) {
  $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $t
  Write-Host $line
  try { Add-Content -Path $log -Value $line -Encoding UTF8 } catch {}
}

W "=== DEMON отдалечена инсталация ==="
W "папка: $installDir"

# 1) лицензен ключ
$key = Read-Host "`nЛицензен ключ (DEMON-... )"
if (-not $key) { W "НЯМА КЛЮЧ — спирам."; pause; exit 1 }
W "ключ получен ($($key.Substring(0, [Math]::Min(12, $key.Length)))...)"

# 2) release инфо
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$rel = Invoke-RestMethod "$base/RELEASE.json"
W "версия на сървъра: $($rel.version)"

# 3) сваляне на пакета + sha256
$zipUrl = "$base/$($rel.installer.file)"
$zip = Join-Path $env:TEMP "swing_live.zip"
W "свалям $zipUrl ..."
Invoke-WebRequest $zipUrl -OutFile $zip -UseBasicParsing
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($sha -ne $rel.installer.sha256) { W "ГРЕШКА: контролната сума НЕ съвпада! Спрян."; pause; exit 2 }
W "контролна сума OK"

# 4) разхивиране в инсталационната папка
W "инсталирам в $installDir ..."
Expand-Archive $zip -DestinationPath $installDir -Force

# 5) Python 3.12
$py = $null
try { $py = (& py -3.12 -c "import sys;print(sys.executable)" 2>$null | Select-Object -Last 1).Trim() } catch {}
if (-not $py -or -not (Test-Path $py)) {
  W "Python липсва — свалям официалния инсталатор (python.org)..."
  $pyExe = Join-Path $env:TEMP "python-3.12.7-amd64.exe"
  if (-not (Test-Path $pyExe)) {
    Invoke-WebRequest "https://martin4o123.github.io/demon-centar/download/python-3.12.7-amd64.exe" -OutFile $pyExe -UseBasicParsing
  }
  W "инсталирам Python (1-2 мин, без прозорци)..."
  Start-Process $pyExe -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0','Include_doc=0' -Wait
  $py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
  if (-not (Test-Path $py)) { W "ГРЕШКА: Python не се инсталира. Инсталирай ръчно от python.org (3.12) и пусни командата пак."; pause; exit 3 }
}
W "Python: $py"

# 6) библиотеки
W "инсталирам библиотеките (flask, MetaTrader5, cryptography)..."
& $py -m pip install --quiet --disable-pip-version-check flask cryptography MetaTrader5
& $py -c "import flask, MetaTrader5, cryptography" 2>$null
if ($LASTEXITCODE -ne 0) { W "ГРЕШКА: библиотеките не се инсталираха. Проверете интернета и пуснете пак."; pause; exit 4 }
W "библиотеките са наред"

# 7) пач на машинните пътища + запазване на ключа
$cfg = Join-Path $installDir "engine\config.json"
if (Test-Path $cfg) {
  $txt = [IO.File]::ReadAllText($cfg, [Text.Encoding]::UTF8)
  $new = [regex]::Replace($txt, 'C:\\Users\\[^\\]+\\AppData\\Local', ($env:LOCALAPPDATA -replace '\\', '\\'))
  if ($new -ne $txt) { [IO.File]::WriteAllText($cfg, $new, (New-Object Text.UTF8Encoding($false))); W "пътищата са пачнати" }
}
try {
  New-Item -ItemType Directory -Path (Join-Path $installDir "config") -Force | Out-Null
  [IO.File]::WriteAllText((Join-Path $installDir "config\license_key.txt"), $key, (New-Object Text.UTF8Encoding($false)))
} catch {}

# 8) стартиране на таблото
W "пускам таблото..."
Start-Process $py -ArgumentList (Join-Path $installDir "dashboard\app.py") -WindowStyle Hidden
Start-Sleep 9
try { Start-Process "http://127.0.0.1:5123" } catch {}
W ""
W "=== ГОТОВО! Таблото: http://127.0.0.1:5123 ==="
W "Ако браузърът не се отвори сам — отвори го ръчно на този адрес."
W "За стартиране след рестарт: пусни пак същата команда (инсталацията е вече направена)."
pause
