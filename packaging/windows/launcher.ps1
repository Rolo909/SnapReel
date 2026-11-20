# Tvorka launcher and first-run installer for Windows.
#
# Started by "Tvorka.cmd" (and by nothing else on the first run). When everything is
# installed it simply starts the app. Otherwise it shows a small window that downloads a
# private Python and the AI components with uv into "runtime\", picking the PyTorch build
# for the graphics card, creates desktop and Start menu shortcuts, and starts the app.
# Nothing is installed system-wide; deleting the Tvorka folder removes everything.

param(
    [switch]$NoLaunch,     # install and create shortcuts, but do not start the app (tests)
    [switch]$Reinstall,    # rebuild the environment even if it looks fine
    [switch]$NoShortcuts,  # do not create desktop / Start menu shortcuts (tests)
    [int]$WaitPid = 0,     # wait for this process (the app asking for a GPU build) to exit first
    [string]$SimulateGpu = '', # tests: pretend these adapters are installed, "Name|VEN_DEV;Name|VEN_DEV"
    [switch]$DetectOnly,   # tests: print the chosen PyTorch build as JSON and exit
    [double]$SimulateFreeSpace = -1 # tests: pretend the disk has this many bytes free
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# ---------------------------------------------------------------- locations
$SetupDir = $PSScriptRoot                       # Tvorka\app\setup
$App      = Split-Path -Parent $SetupDir        # Tvorka\app
$Root     = Split-Path -Parent $App             # Tvorka
$Runtime  = Join-Path $Root 'runtime'
$Venv     = Join-Path $Runtime 'venv'
$Cache    = Join-Path $Runtime 'cache'
$PyHome   = Join-Path $Runtime 'python'
$Marker   = Join-Path $Runtime 'installed.json'
$Log      = Join-Path $Runtime 'install.log'
$Uv       = Join-Path $SetupDir 'uv.exe'
$Pythonw  = Join-Path $Venv 'Scripts\pythonw.exe'
$PythonC  = Join-Path $Venv 'Scripts\python.exe'
$Icon     = Join-Path $App 'src\tvorka\assets\icons\app_icon.ico'

$GpuTable = Join-Path $App 'src\tvorka\data\gpu_support.json'

if ($WaitPid -gt 0) {
    try { Wait-Process -Id $WaitPid -Timeout 60 -ErrorAction Stop } catch { }
}

$init = Get-Content (Join-Path $App 'src\tvorka\__init__.py') -Raw
$Version = if ($init -match '__version__\s*=\s*"([^"]+)"') { $Matches[1] } else { '0' }

function Start-Tvorka {
    Start-Process -FilePath $Pythonw -ArgumentList @('-m', 'tvorka', '--home', "`"$Root`"") `
        -WorkingDirectory $Root
}

# ---------------------------------------------------------------- fast path
if (-not $Reinstall -and -not $DetectOnly -and (Test-Path $Marker) -and (Test-Path $Pythonw)) {
    try {
        $state = Get-Content $Marker -Raw | ConvertFrom-Json
        if ($state.version -eq $Version -and $state.root -eq $Root) {
            if (-not $NoLaunch) { Start-Tvorka }
            exit 0
        }
    } catch { }  # unreadable marker: repair below
}

# ---------------------------------------------------------------- texts
$ru = (Get-UICulture).TwoLetterISOLanguageName -eq 'ru'
function T([string]$en, [string]$rus) { if ($ru) { $rus } else { $en } }

$S = @{
    Title      = 'Tvorka'
    FirstRun   = T 'Getting ready for the first start. This is done only once.' 'Подготовка к первому запуску. Это нужно сделать только один раз.'
    Update     = T 'Updating Tvorka components.' 'Обновляем компоненты Tvorka.'
    Check      = T 'Step 1 of 3 · Checking this computer' 'Шаг 1 из 3 · Проверяем компьютер'
    Download   = T 'Step 2 of 3 · Downloading the AI components' 'Шаг 2 из 3 · Скачиваем компоненты ИИ'
    Finish     = T 'Step 3 of 3 · Finishing' 'Шаг 3 из 3 · Завершаем установку'
    Done       = T 'Done! Tvorka is starting…' 'Готово! Tvorka запускается…'
    Hint       = T 'You can minimize this window. If the download is interrupted, the files already downloaded are kept.' 'Окно можно свернуть. Если загрузка прервётся, уже скачанные файлы сохранятся.'
    Nvidia     = T 'NVIDIA graphics card found: installing the fast GPU version (about {0}).' 'Найдена видеокарта NVIDIA: ставим быструю версию для видеокарты (около {0}).'
    NoNvidia   = T 'No supported graphics card: installing the compact version (about {0}). Models will run on the processor.' 'Подходящей видеокарты нет: ставим компактную версию (около {0}). Модели будут работать на процессоре.'
    OtherGpu   = T '{0} found: installing the version for this graphics card (about {1}).' 'Найдена видеокарта {0}: ставим версию для неё (около {1}).'
    GpuFailed  = T 'The graphics card did not start with the GPU version — usually the driver is too old. Installing the compact version instead (about {0}); models will run on the processor. After updating the driver ({1}), press "Set up Tvorka for the graphics card" in Settings → This computer.' 'Видеокарта не запустилась с версией для неё — обычно из-за старого драйвера. Ставим компактную версию (около {0}); модели будут работать на процессоре. Обновите драйвер ({1}) и нажмите «Настроить Tvorka для видеокарты» в разделе «Настройки → Этот компьютер».'
    OldDriver  = T 'The NVIDIA driver is too old for the GPU version ({0}; 580 or newer is needed). Installing the compact version for now. After updating the driver at nvidia.com, Tvorka offers the GPU version in Settings → This computer.' 'Драйвер NVIDIA слишком старый для версии с видеокартой ({0}; нужен 580 или новее). Пока ставим компактную версию. Обновите драйвер на nvidia.com — после этого Tvorka предложит версию для видеокарты в разделе «Настройки → Этот компьютер».'
    Progress   = T '{0} of about {1} · {2}/s · about {3} left' '{0} из примерно {1} · {2}/с · осталось около {3}'
    Starting   = T 'Starting the download…' 'Начинаем загрузку…'
    Checking   = T 'Checking the installation…' 'Проверяем установку…'
    Shortcuts  = T 'Creating shortcuts on the desktop and in the Start menu…' 'Создаём ярлыки на рабочем столе и в меню «Пуск»…'
    Cancel     = T 'Cancel' 'Отмена'
    Retry      = T 'Try again' 'Повторить'
    Close      = T 'Close' 'Закрыть'
    OpenLog    = T 'Open the log' 'Открыть журнал'
    ErrTitle   = T 'The installation did not finish' 'Установка не завершилась'
    ErrNet     = T 'The internet connection was lost. Check it and press "Try again" — files that were already downloaded are not downloaded again.' 'Пропало подключение к интернету. Проверьте его и нажмите «Повторить» — уже скачанные файлы повторно скачиваться не будут.'
    ErrDisk    = T 'Not enough free space on disk {0}: about {1} is needed, {2} is free. Free some space or move the Tvorka folder to another disk, then press "Try again".' 'Не хватает места на диске {0}: нужно около {1}, свободно {2}. Освободите место или перенесите папку Tvorka на другой диск и нажмите «Повторить».'
    ErrPath    = T 'Tvorka cannot write to its folder. Move the Tvorka folder somewhere you own, for example to "Documents" or D:\, and start it again.' 'Tvorka не может записывать в свою папку. Перенесите папку Tvorka туда, где у вас есть права, например в «Документы» или на D:\, и запустите снова.'
    ErrOther   = T 'Something went wrong. Press "Try again"; if it repeats, open the log and send it to the author.' 'Что-то пошло не так. Нажмите «Повторить»; если ошибка повторится, откройте журнал и отправьте его автору.'
    ErrCheck   = T 'The components were downloaded but do not start. Press "Try again" to repair them.' 'Компоненты скачаны, но не запускаются. Нажмите «Повторить», чтобы восстановить их.'
    Cancelled  = T 'Installation cancelled. Start Tvorka again to continue — files that were already downloaded are kept.' 'Установка отменена. Запустите Tvorka снова, чтобы продолжить — уже скачанные файлы сохранятся.'
    Minutes    = T '{0} min' '{0} мин'
    LessMinute = T 'less than a minute' 'меньше минуты'
    GB         = T '{0:N1} GB' '{0:N1} ГБ'
    MB         = T '{0:N0} MB' '{0:N0} МБ'
}

function Format-Size([double]$bytes) {
    if ($bytes -ge 1GB) { return ($S.GB -f ($bytes / 1GB)) }
    return ($S.MB -f ($bytes / 1MB))
}

# ---------------------------------------------------------------- window
$colors = @{
    Bg = [System.Drawing.ColorTranslator]::FromHtml('#13171D'); Text = [System.Drawing.ColorTranslator]::FromHtml('#E8ECF1')
    Muted = [System.Drawing.ColorTranslator]::FromHtml('#9AA4B2'); Faint = [System.Drawing.ColorTranslator]::FromHtml('#667080')
    Line = [System.Drawing.ColorTranslator]::FromHtml('#262C36'); Accent = [System.Drawing.ColorTranslator]::FromHtml('#34D3A6')
    OnAccent = [System.Drawing.ColorTranslator]::FromHtml('#04261D'); Bad = [System.Drawing.ColorTranslator]::FromHtml('#F2686A')
    Raised = [System.Drawing.ColorTranslator]::FromHtml('#1A1F27')
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Tvorka'
$form.ClientSize = New-Object System.Drawing.Size(600, 360)
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.StartPosition = 'CenterScreen'
$form.BackColor = $colors.Bg
$form.ForeColor = $colors.Text
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$form.AutoScaleMode = 'Dpi'
if (Test-Path $Icon) { $form.Icon = New-Object System.Drawing.Icon($Icon) }

function New-Label([int]$y, [int]$h, $font, $color) {
    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(32, $y)
    $label.Size = New-Object System.Drawing.Size(536, $h)
    $label.ForeColor = $color
    if ($font) { $label.Font = $font }
    $form.Controls.Add($label)
    return $label
}

$title    = New-Label 24 40 (New-Object System.Drawing.Font('Segoe UI Semibold', 18)) $colors.Text
$title.Text = $S.Title
$subtitle = New-Label 66 24 $null $colors.Muted
$step     = New-Label 112 26 (New-Object System.Drawing.Font('Segoe UI Semibold', 11)) $colors.Text
$detail   = New-Label 140 70 $null $colors.Muted

$track = New-Object System.Windows.Forms.Panel
$track.Location = New-Object System.Drawing.Point(32, 218)
$track.Size = New-Object System.Drawing.Size(536, 8)
$track.BackColor = $colors.Line
$bar = New-Object System.Windows.Forms.Panel
$bar.Location = New-Object System.Drawing.Point(0, 0)
$bar.Size = New-Object System.Drawing.Size(0, 8)
$bar.BackColor = $colors.Accent
$track.Controls.Add($bar)
$form.Controls.Add($track)

$hint = New-Label 238 44 (New-Object System.Drawing.Font('Segoe UI', 9)) $colors.Faint
$hint.Text = $S.Hint

function New-Button([string]$text, [int]$x, [bool]$primary) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $text
    $button.Location = New-Object System.Drawing.Point($x, 302)
    $button.Size = New-Object System.Drawing.Size(130, 36)
    $button.FlatStyle = 'Flat'
    $button.FlatAppearance.BorderSize = if ($primary) { 0 } else { 1 }
    $button.FlatAppearance.BorderColor = $colors.Line
    $button.BackColor = if ($primary) { $colors.Accent } else { $colors.Raised }
    $button.ForeColor = if ($primary) { $colors.OnAccent } else { $colors.Text }
    $button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $form.Controls.Add($button)
    return $button
}

$cancelButton = New-Button $S.Cancel 438 $false
$retryButton  = New-Button $S.Retry 298 $true
$logButton    = New-Button $S.OpenLog 32 $false
$retryButton.Visible = $false
$logButton.Visible = $false

function Set-Progress([double]$fraction) {
    $fraction = [Math]::Max(0.0, [Math]::Min(1.0, $fraction))
    $bar.Width = [int]($track.Width * $fraction)
}

function Pump { [System.Windows.Forms.Application]::DoEvents() }

# ---------------------------------------------------------------- state
$script:proc = $null
$script:flavor = 'cpu'
$script:python = ''
$script:gpuFailed = $false
$script:expected = 1.4GB
$script:lastBytes = 0.0
$script:lastTime = [DateTime]::Now
$script:speed = 0.0
$script:failed = $false

function Write-Log([string]$text) {
    Add-Content -Path $Log -Value ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $text) -Encoding UTF8
}

function Get-FolderBytes([string]$path) {
    if (-not (Test-Path $path)) { return 0.0 }
    $sum = 0.0
    try {
        foreach ($file in [System.IO.Directory]::EnumerateFiles($path, '*', 'AllDirectories')) {
            try { $sum += (New-Object System.IO.FileInfo($file)).Length } catch { }
        }
    } catch { }
    return $sum
}

function Show-Error([string]$message) {
    $script:failed = $true
    $step.Text = $S.ErrTitle
    $step.ForeColor = $colors.Bad
    $detail.Text = $message
    $detail.Height = 96
    $hint.Visible = $false
    $track.Visible = $false
    $retryButton.Visible = $true
    $logButton.Visible = (Test-Path $Log)
    $cancelButton.Text = $S.Close
    Write-Log "ERROR: $message"
}

function Get-NvidiaDriver {
    # Win32 reports e.g. 32.0.15.8180 for driver 581.80: the last five digits are the version.
    if ($SimulateGpu) {
        if ($SimulateGpu -match 'NVIDIA[^|;]*\|[^;]*DRV_(\d+)') { return [double]$Matches[1] }
        return $null
    }
    foreach ($gpu in Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue) {
        if ($gpu.Name -match 'NVIDIA') {
            $digits = ($gpu.DriverVersion -replace '\.', '')
            if ($digits.Length -ge 5) {
                $tail = $digits.Substring($digits.Length - 5)
                return [double]("{0}.{1}" -f $tail.Substring(0, 3), $tail.Substring(3))
            }
            return 0.0
        }
    }
    return $null
}

function Get-Adapters {
    # Name and PCI ids of every display adapter (or the simulated ones in tests).
    if ($SimulateGpu) {
        foreach ($item in $SimulateGpu -split ';') {
            $name, $ids = $item -split '\|', 2
            [pscustomobject]@{ Name = $name; Vendor = ($ids -replace '^VEN_([0-9A-F]{4}).*$', '$1'); Device = ($ids -replace '^.*DEV_([0-9A-F]{4}).*$', '$1') }
        }
        return
    }
    foreach ($gpu in Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue) {
        $vendor = ''; $device = ''
        if ($gpu.PNPDeviceID -match 'VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})') { $vendor = $Matches[1]; $device = $Matches[2] }
        [pscustomobject]@{ Name = [string]$gpu.Name; Vendor = $vendor; Device = $device }
    }
}

function Find-GpuBuild {
    # The AMD / Intel adapter with a PyTorch build (see gpu_support.json): discrete first, AMD before Intel.
    $table = Get-Content $GpuTable -Raw -Encoding UTF8 | ConvertFrom-Json
    $best = $null; $bestRank = -1
    foreach ($adapter in Get-Adapters) {
        $vendor = if ($adapter.Vendor -in '1002', '1022' -or $adapter.Name -match 'AMD|Radeon') { 'amd' }
                  elseif ($adapter.Vendor -eq '8086' -or $adapter.Name -match 'Intel') { 'intel' } else { '' }
        if (-not $vendor) { continue }
        foreach ($row in $table.$vendor) {
            if ($row.ids -contains $adapter.Device -or $adapter.Name -match $row.name) {
                $rank = $(if ($row.integrated) { 0 } else { 2 }) + $(if ($vendor -eq 'amd') { 1 } else { 0 })
                if ($rank -gt $bestRank) {
                    $bestRank = $rank
                    $python = if ($row.flavor -like 'rocm-*') { $table.python.rocm } else { '' }
                    $best = [pscustomobject]@{ Name = $adapter.Name; Vendor = $vendor; Flavor = $row.flavor; Python = $python }
                }
                break
            }
        }
    }
    return $best
}

function Test-Internet {
    try {
        $request = [System.Net.WebRequest]::Create('https://pypi.org/simple/')
        $request.Method = 'HEAD'
        $request.Timeout = 10000
        $response = $request.GetResponse()
        $response.Close()
        return $true
    } catch { return $false }
}

# ---------------------------------------------------------------- the steps
function Start-Install {
    $script:failed = $false
    $step.ForeColor = $colors.Text
    $detail.Height = 70
    $hint.Visible = $true
    $track.Visible = $true
    $retryButton.Visible = $false
    $logButton.Visible = $false
    $cancelButton.Text = $S.Cancel
    $subtitle.Text = if (Test-Path $Marker) { $S.Update } else { $S.FirstRun }

    # 1. this computer ------------------------------------------------------------
    $step.Text = $S.Check
    $detail.Text = ''
    Set-Progress 0.02
    Pump
    try {
        New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
        Write-Log "Tvorka $Version, root $Root"
        # Files from a downloaded zip are marked "from the internet"; uv.exe must run silently.
        Get-ChildItem -Path $App -Recurse -File -ErrorAction SilentlyContinue |
            Unblock-File -ErrorAction SilentlyContinue
        Get-ChildItem -Path $Root -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
    } catch {
        Show-Error $S.ErrPath
        return
    }

    $driver = Get-NvidiaDriver
    $other = Find-GpuBuild
    $note = ''
    $script:python = ''
    if ($null -ne $driver -and $driver -ge 580) {
        $script:flavor = 'cu130'; $script:expected = 4.3GB
        $note = $S.Nvidia -f (Format-Size 3GB)
    } elseif ($null -ne $other -and -not $script:gpuFailed) {
        $script:flavor = $other.Flavor; $script:python = $other.Python
        if ($other.Vendor -eq 'amd') { $script:expected = 4.6GB; $size = 2.5GB } else { $script:expected = 3.4GB; $size = 2GB }
        $note = $S.OtherGpu -f $other.Name, (Format-Size $size)
    } elseif ($script:gpuFailed) {
        $script:flavor = 'cpu'; $script:expected = 2.0GB
        $site = if ($null -ne $other -and $other.Vendor -eq 'intel') { 'intel.com' } elseif ($null -ne $other) { 'amd.com' } else { 'nvidia.com' }
        $note = $S.GpuFailed -f (Format-Size 0.8GB), $site
    } elseif ($null -ne $driver) {
        $script:flavor = 'cpu'; $script:expected = 2.0GB
        $note = $S.OldDriver -f $driver
    } else {
        $script:flavor = 'cpu'; $script:expected = 2.0GB
        $note = $S.NoNvidia -f (Format-Size 0.8GB)
    }
    # AMD builds exist for an older Python only; a processor fallback keeps that Python.
    if ($script:gpuFailed -and $script:failedPython) { $script:python = $script:failedPython }
    Write-Log "flavor $($script:flavor), python '$($script:python)', NVIDIA driver: $driver, other GPU: $($other.Name)"
    # A previous run with the other flavour leaves its torch in the cache; that is fine.
    $done = Get-FolderBytes $Cache
    $need = [Math]::Max(0.5GB, $script:expected - $done) + 1GB
    $drive = New-Object System.IO.DriveInfo((Split-Path -Qualifier $Root))
    $free = if ($SimulateFreeSpace -ge 0) { $SimulateFreeSpace } else { $drive.AvailableFreeSpace }
    if ($free -lt $need) {
        Show-Error ($S.ErrDisk -f $drive.Name, (Format-Size $need), (Format-Size $free))
        return
    }
    if (-not (Test-Internet)) {
        Show-Error $S.ErrNet
        return
    }

    # The environment remembers absolute paths: a moved folder needs a fresh one (from the cache).
    if (Test-Path $Marker) {
        try {
            $state = Get-Content $Marker -Raw | ConvertFrom-Json
            if ($state.root -ne $Root -or $state.flavor -ne $script:flavor -or "$($state.python)" -ne $script:python) {
                Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    if ($Reinstall) { Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue }

    # 2. download -------------------------------------------------------------------
    $step.Text = $S.Download
    $detail.Text = $note + "`n" + $S.Starting
    Set-Progress 0.04
    Pump
    $env:UV_CACHE_DIR = $Cache
    $env:UV_PYTHON_INSTALL_DIR = $PyHome
    $env:UV_PROJECT_ENVIRONMENT = $Venv
    $env:UV_PYTHON_PREFERENCE = 'only-managed'   # never touch a Python the user may have
    $env:UV_HTTP_TIMEOUT = '300'
    $env:UV_NO_PROGRESS = '1'
    # One download at a time: uv keeps only finished files when the connection is lost.
    $env:UV_CONCURRENT_DOWNLOADS = '1'
    if ($script:python) { $env:UV_PYTHON = $script:python } else { Remove-Item Env:UV_PYTHON -ErrorAction SilentlyContinue }
    $arguments = @('sync', '--project', "`"$App`"", '--frozen', '--no-dev', '--no-editable',
                   '--extra', $script:flavor, '--extra', 'online', '--extra', 'docs')
    Write-Log ("uv " + ($arguments -join ' '))
    $script:proc = Start-Process -FilePath $Uv -ArgumentList $arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardError (Join-Path $Runtime 'uv-stderr.log') `
        -RedirectStandardOutput (Join-Path $Runtime 'uv-stdout.log')
    # Windows PowerShell only reports ExitCode for processes whose handle was opened while
    # they ran; touching .Handle here keeps it.
    $null = $script:proc.Handle
    $script:lastBytes = Get-FolderBytes $Cache
    $script:lastTime = [DateTime]::Now
    $script:speed = 0.0
    $script:note = $note
    $timer.Start()
}

function Update-Download {
    if ($null -eq $script:proc) { return }
    $bytes = (Get-FolderBytes $Cache) + (Get-FolderBytes $PyHome)
    $now = [DateTime]::Now
    $seconds = ($now - $script:lastTime).TotalSeconds
    if ($seconds -ge 1) {
        $fresh = [Math]::Max(0.0, ($bytes - $script:lastBytes) / $seconds)
        $script:speed = if ($script:speed -eq 0) { $fresh } else { $script:speed * 0.7 + $fresh * 0.3 }
        $script:lastBytes = $bytes
        $script:lastTime = $now
    }
    $fraction = [Math]::Min(0.97, $bytes / $script:expected)
    Set-Progress (0.04 + 0.86 * $fraction)
    $left = if ($script:speed -gt 1MB) { ($script:expected - $bytes) / $script:speed } else { -1 }
    $eta = if ($left -lt 0) { '…' } elseif ($left -lt 60) { $S.LessMinute } else { $S.Minutes -f [int][Math]::Ceiling($left / 60) }
    $detail.Text = $script:note + "`n" + ($S.Progress -f (Format-Size $bytes), (Format-Size $script:expected), (Format-Size $script:speed), $eta)

    if ($script:proc.HasExited) {
        $timer.Stop()
        $script:proc.WaitForExit()
        $code = $script:proc.ExitCode
        $errors = ''
        foreach ($name in 'uv-stderr.log', 'uv-stdout.log') {
            $path = Join-Path $Runtime $name
            if (Test-Path $path) {
                $text = Get-Content $path -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
                if ($text) { Add-Content -Path $Log -Value $text -Encoding UTF8; $errors += $text }
            }
        }
        $script:proc = $null
        Write-Log "uv exit code $code"
        if ($script:cancelled) { return }
        if ($code -ne 0) {
            # Classify by the error lines only: the package list mentions e.g. "networkx".
            $errors = (($errors -split "`r?`n") | Where-Object { $_ -match '(?i)^\s*(error|caused by|[│├╰×]|failed)' }) -join "`n"
            if ($errors -match '(?i)os error 112|not enough space|no space') {
                $drive = New-Object System.IO.DriveInfo((Split-Path -Qualifier $Root))
                Show-Error ($S.ErrDisk -f $drive.Name, (Format-Size ($script:expected / 2)), (Format-Size $drive.AvailableFreeSpace))
            } elseif ($errors -match '(?i)failed to fetch|dns|timed out|connect|network|tls|certificate|request failed|sending request|tunnel|end of file|reset by peer') {
                Show-Error $S.ErrNet
            } elseif ($errors -match '(?i)access is denied|permission denied|os error 5\b') {
                Show-Error $S.ErrPath
            } else {
                Show-Error $S.ErrOther
            }
            return
        }
        Complete-Install
    }
}

function Complete-Install {
    # 3. check and shortcuts -------------------------------------------------------
    $step.Text = $S.Finish
    $detail.Text = $S.Checking
    Set-Progress 0.93
    Pump
    $probe = Join-Path $Runtime 'check.py'
    Set-Content -Path $probe -Encoding UTF8 -Value @(
        'import PySide6, diffusers, tvorka, torch',
        'xpu = getattr(torch, "xpu", None)',
        'print("gpu" if torch.cuda.is_available() or (xpu is not None and xpu.is_available()) else "cpu")')
    $check = Start-Process -FilePath $PythonC -ArgumentList @("`"$probe`"") -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardError (Join-Path $Runtime 'check.log') -RedirectStandardOutput (Join-Path $Runtime 'check.out')
    $device = (Get-Content (Join-Path $Runtime 'check.out') -Raw -ErrorAction SilentlyContinue)
    Write-Log "check: exit $($check.ExitCode), device $device"
    if ($check.ExitCode -ne 0) {
        Add-Content -Path $Log -Value (Get-Content (Join-Path $Runtime 'check.log') -Raw) -Encoding UTF8
        Show-Error $S.ErrCheck
        return
    }
    if ($script:flavor -ne 'cpu' -and "$device".Trim() -ne 'gpu' -and -not $script:gpuFailed) {
        # Typically an old graphics driver: fall back to the processor build rather than a dead end.
        Write-Log "the $($script:flavor) build cannot use the graphics card; installing the processor build"
        $script:gpuFailed = $true
        $script:failedPython = $script:python
        Start-Install
        return
    }
    $detail.Text = $S.Shortcuts
    Set-Progress 0.97
    Pump
    if (-not $NoShortcuts) { try {
        $shell = New-Object -ComObject WScript.Shell
        $places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
        foreach ($folder in $places) {
            # Tvorka was called SnapReel up to 1.0: its shortcuts would start the old version.
            Remove-Item -LiteralPath (Join-Path $folder 'SnapReel.lnk') -ErrorAction SilentlyContinue
            $link = $shell.CreateShortcut((Join-Path $folder 'Tvorka.lnk'))
            $link.TargetPath = $Pythonw
            $link.Arguments = "-m tvorka --home `"$Root`""
            $link.WorkingDirectory = $Root
            $link.Description = 'Tvorka'
            if (Test-Path $Icon) { $link.IconLocation = "$Icon,0" }
            $link.Save()
        }
    } catch {
        Write-Log "shortcuts: $_"   # not fatal: Tvorka.cmd still works
    } }
    @{ version = $Version; root = $Root; flavor = $script:flavor; python = $script:python
       gpu_failed = $script:gpuFailed; date = (Get-Date -Format s) } |
        ConvertTo-Json | Set-Content -Path $Marker -Encoding UTF8
    Write-Log 'installed'
    $step.Text = $S.Done
    $detail.Text = ''
    Set-Progress 1.0
    Pump
    if (-not $NoLaunch) { Start-Tvorka }
    Start-Sleep -Milliseconds 1200
    $form.Close()
}

if ($DetectOnly) {
    $gpu = Find-GpuBuild
    $driver = Get-NvidiaDriver
    $flavor = if ($null -ne $driver -and $driver -ge 580) { 'cu130' } elseif ($null -ne $gpu) { $gpu.Flavor } else { 'cpu' }
    $python = if ($flavor -ne 'cu130' -and $null -ne $gpu) { $gpu.Python } else { '' }
    [Console]::Out.Write((@{ flavor = $flavor; python = $python; gpu = "$($gpu.Name)"; nvidia = $driver } | ConvertTo-Json -Compress))
    exit 0
}

# ---------------------------------------------------------------- wiring
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({ Update-Download })

$script:cancelled = $false
$script:failedPython = ''
$cancelButton.Add_Click({
    if ($script:failed) { $form.Close(); return }
    $script:cancelled = $true
    $timer.Stop()
    if ($null -ne $script:proc -and -not $script:proc.HasExited) {
        & taskkill.exe /T /F /PID $script:proc.Id | Out-Null
    }
    Write-Log 'cancelled by the user'
    [System.Windows.Forms.MessageBox]::Show($S.Cancelled, 'Tvorka') | Out-Null
    $form.Close()
})
$retryButton.Add_Click({ Start-Install })
$logButton.Add_Click({ if (Test-Path $Log) { Start-Process notepad.exe -ArgumentList "`"$Log`"" } })
$form.Add_FormClosing({
    if ($null -ne $script:proc -and -not $script:proc.HasExited) {
        & taskkill.exe /T /F /PID $script:proc.Id | Out-Null
    }
})
$form.Add_Shown({ Start-Install })
[void]$form.ShowDialog()
