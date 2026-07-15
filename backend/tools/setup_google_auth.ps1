# setup_google_auth.ps1
# Logowanie Google dla KupujPL Gry (kupujpl.pl/games) - bez karty (Firebase Spark / Google Cloud bez billing).
# OAuth Web Client ID tworzy sie tylko po zalogowaniu do Google - tego kroku nie da sie zautomatyzowac.

$ErrorActionPreference = "Stop"
$BackendRoot = Split-Path $PSScriptRoot -Parent
$VpsEnvPath = "/opt/kupujpl-games/.env"

Write-Host ""
Write-Host "=== KupujPL Gry - налаштування Google Sign-In ===" -ForegroundColor Cyan
Write-Host ""

$urls = @(
    "https://console.firebase.google.com/",
    "https://console.cloud.google.com/apis/credentials"
)
foreach ($u in $urls) {
    Write-Host "Відкриваю: $u"
    Start-Process $u
}

Write-Host ""
Write-Host @"
ІНСТРУКЦІЯ (5 кроків) — безкоштовно, без кредитної картки (план Firebase Spark):

1) Увійдіть у Google і відкрийте Firebase Console (перше посилання вище).
   Створіть проєкт (або оберіть існуючий). На кроці плану оберіть Spark — без оплати.

2) У проєкті Firebase: Build → Authentication → Get started → увімкніть провайдер «Google» і збережіть.

3) Project settings (шестерня) → Your apps → додайте Web-додаток (іконка </>).
   Псевдонім, наприклад: kupujpl-games. Скопіюйте значення «Web client ID»
   (закінчується на .apps.googleusercontent.com) — це GOOGLE_CLIENT_ID.

4) У Google Cloud Console → Credentials → ваш OAuth 2.0 Client ID (Web):
   Authorized JavaScript origins:
     https://kupujpl.pl
   Authorized redirect URIs (за потреби):
     https://kupujpl.pl
     https://kupujpl.pl/games/

5) На VPS додайте рядок до $VpsEnvPath :
     GOOGLE_CLIENT_ID=<ваш Web client ID>
   Потім перезапустіть сервіс:
     sudo systemctl restart kupujpl-games
   Перевірка:
     curl -sS https://kupujpl.pl/games/api/auth/google-config
   Очікується: {"enabled":true,"client_id":"..."}
"@ -ForegroundColor Yellow

$cid = Read-Host "Вставте Web client ID тут (Enter - пропустити автодеплой на VPS)"
if ([string]::IsNullOrWhiteSpace($cid)) {
    Write-Host "Готово. Після ручного додавання GOOGLE_CLIENT_ID на VPS перезапустіть kupujpl-games." -ForegroundColor Green
    exit 0
}

$cid = $cid.Trim()
if ($cid -notmatch '\.apps\.googleusercontent\.com$') {
    Write-Host "Попередження: ID не схожий на типовий Web client ID Google." -ForegroundColor DarkYellow
}

$localEnv = Join-Path $BackendRoot ".env"
if (-not (Test-Path $localEnv)) {
    "# local dev`nGOOGLE_CLIENT_ID=$cid" | Set-Content -Encoding utf8 $localEnv
    Write-Host "Збережено локально: $localEnv" -ForegroundColor Green
} else {
    $lines = Get-Content $localEnv -ErrorAction SilentlyContinue
    $found = $false
    $newLines = foreach ($line in $lines) {
        if ($line -match '^GOOGLE_CLIENT_ID=') {
            $found = $true
            "GOOGLE_CLIENT_ID=$cid"
        } else { $line }
    }
    if (-not $found) { $newLines += "GOOGLE_CLIENT_ID=$cid" }
    $newLines | Set-Content -Encoding utf8 $localEnv
    Write-Host "Оновлено локально: $localEnv" -ForegroundColor Green
}

Write-Host "Деплой GOOGLE_CLIENT_ID на VPS..." -ForegroundColor Cyan
$tmpPy = Join-Path $env:TEMP "kupujpl_set_google_env.py"
$pyBody = @
import sys
sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
import ssh_exec
cid = sys.argv[1]
path = "/opt/kupujpl-games/.env"
r = ssh_exec.read_file(path)
content = r.get("content") or ""
lines = content.splitlines()
out = []
found = False
for line in lines:
    if line.startswith("GOOGLE_CLIENT_ID="):
        out.append(f"GOOGLE_CLIENT_ID={cid}")
        found = True
    else:
        out.append(line)
if not found:
    if out and out[-1].strip():
        out.append("")
    out.append(f"GOOGLE_CLIENT_ID={cid}")
new_content = "\n".join(out) + ("\n" if out else "")
ssh_exec.write_file(path, new_content)
restart = ssh_exec.run_command("systemctl restart kupujpl-games && sleep 2 && systemctl is-active kupujpl-games")
print("service:", (restart.get("stdout") or "").strip())
api = ssh_exec.run_command("curl -sS -m 15 https://kupujpl.pl/games/api/auth/google-config")
print("google-config:", (api.get("stdout") or "").strip())
''@
Set-Content -Encoding utf8 -Path $tmpPy -Value $pyBody
python $tmpPy $cid
Remove-Item $tmpPy -ErrorAction SilentlyContinue
Write-Host "Завершено." -ForegroundColor Green