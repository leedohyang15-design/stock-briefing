@echo off
REM 평일 07:55 작업 스케줄러 등록용. 처음 1~2일은 --dry-run 으로 실행하세요.
cd /d %~dp0..
python -m src.trader.run_day %* >> data\trader_%date:~0,4%%date:~5,2%%date:~8,2%.log 2>&1
