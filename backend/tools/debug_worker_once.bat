@echo off
cd /d C:\Users\dear2\kupujpl-games\backend
set GAMES_API_URL=https://kupujpl.pl/games
set PANEL3_ACCESS_CODE=1408
set PYTHONWARNINGS=ignore::DeprecationWarning
set PYTHONIOENCODING=utf-8
echo START %TIME%> tmp\worker_fresh.log
python -u tools\tier_a_scan_worker.py --worker laptop --parallel 2 >> tmp\worker_fresh.log 2>&1
echo EXIT %ERRORLEVEL% %TIME%>> tmp\worker_fresh.log
