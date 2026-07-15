@echo off
cd /d C:\Users\dear2\kupujpl-games\backend
set GAMES_API_URL=https://kupujpl.pl/games
set PANEL3_ACCESS_CODE=1408
set SCAN_PARALLEL=4
set TIER_A_LAPTOP_PARALLEL=4
set TIER_A_G2A_PARALLEL=1
set G2A_REQUEST_DELAY_SEC=3.0
set G2A_403_COOLDOWN_SEC=90
set G2A_PHASE_PAUSE_SEC=300
set G2A_MAX_PRODUCT_TRIES=2
set PYTHONWARNINGS=ignore::DeprecationWarning
set PYTHONIOENCODING=utf-8
set LOGFILE=tmp\tier_a_gentle_worker.log
echo === start %DATE% %TIME% ===>> %LOGFILE%
python -u tools\tier_a_scan_worker.py --worker laptop --parallel 4 >> %LOGFILE% 2>&1
echo === exit %ERRORLEVEL% %DATE% %TIME% ===>> %LOGFILE%
