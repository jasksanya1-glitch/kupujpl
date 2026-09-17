# KupujPL - floating desktop HUD while PC Tier-A scan is running.
# -WatchForever: stay in background, show during scan, hide when finished.
# Without switch: show during scan, exit process when finished.
param(
    [switch]$WatchForever
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$mutex = New-Object System.Threading.Mutex($false, "Global\KupujPL.PcScanHud")
if (-not $mutex.WaitOne(0, $false)) {
    exit 0
}

$root = Split-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) -Parent
$statePath = Join-Path $root "tmp\pc_scan_state.json"
$script:tick = 0
$script:idleCloseAt = $null
$script:drag = $false
$script:dragOrigin = New-Object System.Drawing.Point 0, 0
$script:wasRunning = $false
$script:missedChecks = 0

function Test-PcScanRunning {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and ($_.CommandLine -match 'tier_a_scan_worker\.py\s+--worker\s+pc')
    }
    return [bool]$procs
}

function Get-ScanState {
    if (-not (Test-Path $statePath)) { return $null }
    try {
        return Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "KupujPL Scan"
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(8, 10, 14)
$form.Size = New-Object System.Drawing.Size(280, 118)
$form.Opacity = $(if ($WatchForever) { 0.0 } else { 0.94 })
$form.ShowInTaskbar = $false

$wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$form.Location = New-Object System.Drawing.Point(($wa.Right - $form.Width - 18), ($wa.Bottom - $form.Height - 18))

$panel = New-Object System.Windows.Forms.Panel
$panel.Dock = [System.Windows.Forms.DockStyle]::Fill
$panel.BackColor = [System.Drawing.Color]::FromArgb(8, 10, 14)
$form.Controls.Add($panel)

$title = New-Object System.Windows.Forms.Label
$title.Text = "KUPUJPL  ·  SCAN"
$title.ForeColor = [System.Drawing.Color]::FromArgb(252, 238, 9)
$title.Font = New-Object System.Drawing.Font("Segoe UI", 10.5, [System.Drawing.FontStyle]::Bold)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(48, 12)
$panel.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "Starting..."
$status.ForeColor = [System.Drawing.Color]::FromArgb(230, 226, 210)
$status.Font = New-Object System.Drawing.Font("Segoe UI", 8.5)
$status.AutoSize = $false
$status.Size = New-Object System.Drawing.Size(210, 18)
$status.Location = New-Object System.Drawing.Point(48, 36)
$panel.Controls.Add($status)

$progressLbl = New-Object System.Windows.Forms.Label
$progressLbl.Text = "-"
$progressLbl.ForeColor = [System.Drawing.Color]::FromArgb(0, 240, 255)
$progressLbl.Font = New-Object System.Drawing.Font("Consolas", 9, [System.Drawing.FontStyle]::Bold)
$progressLbl.AutoSize = $false
$progressLbl.Size = New-Object System.Drawing.Size(210, 16)
$progressLbl.Location = New-Object System.Drawing.Point(48, 56)
$panel.Controls.Add($progressLbl)

$barBg = New-Object System.Windows.Forms.Panel
$barBg.BackColor = [System.Drawing.Color]::FromArgb(30, 34, 42)
$barBg.Location = New-Object System.Drawing.Point(48, 78)
$barBg.Size = New-Object System.Drawing.Size(210, 8)
$panel.Controls.Add($barBg)

$barFg = New-Object System.Windows.Forms.Panel
$barFg.BackColor = [System.Drawing.Color]::FromArgb(252, 238, 9)
$barFg.Location = New-Object System.Drawing.Point(0, 0)
$barFg.Size = New-Object System.Drawing.Size(2, 8)
$barBg.Controls.Add($barFg)

$canvas = New-Object System.Windows.Forms.Panel
$canvas.Location = New-Object System.Drawing.Point(8, 14)
$canvas.Size = New-Object System.Drawing.Size(34, 34)
$canvas.BackColor = [System.Drawing.Color]::FromArgb(8, 10, 14)
$panel.Controls.Add($canvas)

$closeBtn = New-Object System.Windows.Forms.Label
$closeBtn.Text = "x"
$closeBtn.ForeColor = [System.Drawing.Color]::FromArgb(140, 140, 140)
$closeBtn.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$closeBtn.AutoSize = $true
$closeBtn.Cursor = [System.Windows.Forms.Cursors]::Hand
$closeBtn.Location = New-Object System.Drawing.Point(252, 4)
$closeBtn.Add_Click({ $form.Close() })
$panel.Controls.Add($closeBtn)

$panel.Add_MouseDown({
    param($s, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        $script:drag = $true
        $script:dragOrigin = $e.Location
    }
})
$panel.Add_MouseMove({
    param($s, $e)
    if ($script:drag) {
        $form.Location = New-Object System.Drawing.Point(
            ($form.Location.X + $e.X - $script:dragOrigin.X),
            ($form.Location.Y + $e.Y - $script:dragOrigin.Y)
        )
    }
})
$panel.Add_MouseUp({ $script:drag = $false })

$canvas.Add_Paint({
    param($s, $e)
    $g = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $cx = 17; $cy = 17
    $pulse = [math]::Abs([math]::Sin($script:tick / 6.0))
    $r = 8 + [int](4 * $pulse)
    $alpha = [int](80 + 140 * $pulse)
    $penRing = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb($alpha, 0, 240, 255)), 2
    $g.DrawEllipse($penRing, ($cx - $r), ($cy - $r), (2 * $r), (2 * $r))
    $penRing.Dispose()

    $sweep = ($script:tick * 12) % 360
    $penArc = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(252, 238, 9)), 2.6
    $penArc.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $penArc.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $g.DrawArc($penArc, 4, 4, 26, 26, $sweep, 110)
    $penArc.Dispose()

    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(0, 240, 255))
    $g.FillEllipse($brush, ($cx - 3), ($cy - 3), 6, 6)
    $brush.Dispose()
})

function Show-HudUi {
    if (-not $form.Visible) { $form.Show() }
    $form.TopMost = $true
    $form.Opacity = 0.94
    $timer.Interval = 250
}

function Hide-Or-Exit {
    if ($WatchForever) {
        $form.Hide()
        $script:idleCloseAt = $null
        $script:wasRunning = $false
        $timer.Interval = 2000
    } else {
        $timer.Stop()
        $form.Close()
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 2000
$timer.Add_Tick({
    $script:tick++
    if ($form.Visible) { $canvas.Invalidate() }

    $running = Test-PcScanRunning
    $st = Get-ScanState

    # Process is the source of truth: appear only while worker runs.
    if ($running) {
        $script:missedChecks = 0
        $script:wasRunning = $true
        $script:idleCloseAt = $null
        Show-HudUi

        $phase = "scanning..."
        if ($st -and $st.scan_subphase) { $phase = [string]$st.scan_subphase }
        elseif ($st -and $st.phase) { $phase = [string]$st.phase }
        if ($phase.Length -gt 34) { $phase = $phase.Substring(0, 34) + "..." }
        $status.Text = $phase

        $done = 0; $total = 0
        if ($st) {
            $done = [int]($st.games_done)
            $total = [int]($st.games_total)
        }
        if ($total -gt 0) {
            $pct = [math]::Min(100.0, [math]::Round(100.0 * $done / $total, 1))
            $gpm = $null
            if ($st) { $gpm = $st.games_per_min }
            $extra = ""
            if ($gpm) { $extra = " | $gpm/min" }
            $progressLbl.Text = ("{0} / {1}  ({2}%){3}" -f $done, $total, $pct, $extra)
            $barFg.Width = [math]::Max(2, [int]($barBg.Width * $pct / 100.0))
        } else {
            $progressLbl.Text = "Scanning..."
            $barFg.Width = [int](20 + 20 * [math]::Abs([math]::Sin($script:tick / 5.0)))
        }
        return
    }

    # Worker gone: require a couple of misses (process list can flicker).
    $script:missedChecks++
    if ($script:missedChecks -lt 2 -and $script:wasRunning) {
        return
    }

    if ($script:wasRunning -or $form.Visible) {
        $status.Text = "Scan finished"
        $progressLbl.Text = "OK"
        $barFg.Width = $barBg.Width
        if ($form.Visible -and -not $script:idleCloseAt) {
            $script:idleCloseAt = [datetime]::UtcNow.AddSeconds(3)
        }
        if ($script:idleCloseAt -and ([datetime]::UtcNow -ge $script:idleCloseAt)) {
            Hide-Or-Exit
        } elseif (-not $form.Visible) {
            Hide-Or-Exit
        }
    } elseif (-not $WatchForever) {
        # Launched but scan already gone.
        Hide-Or-Exit
    } else {
        $timer.Interval = 2000
    }
})

$form.Add_Shown({
    $timer.Start()
    # If WatchForever and no scan yet, hide immediately.
    if ($WatchForever -and -not (Test-PcScanRunning)) {
        $form.Hide()
        $timer.Interval = 2000
    }
})
$form.Add_FormClosed({
    $timer.Stop()
    try { $mutex.ReleaseMutex() } catch {}
    $mutex.Dispose()
})
$form.Add_Paint({
    param($s, $e)
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(252, 238, 9)), 2
    $e.Graphics.DrawRectangle($pen, 1, 1, ($form.Width - 3), ($form.Height - 3))
    $pen.Dispose()
})

[System.Windows.Forms.Application]::EnableVisualStyles()
# Create handle, then run. WatchForever starts hidden via Shown handler.
[System.Windows.Forms.Application]::Run($form)
