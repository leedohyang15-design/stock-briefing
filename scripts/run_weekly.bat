@echo off
REM 토요일 10:00 작업 스케줄러 등록용 (주간 복기 + 변경안 텔레그램 전송 후 /apply 대기)
cd /d %~dp0..
python -m src.trader.run_weekly %* >> data\weekly.log 2>&1
