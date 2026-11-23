@echo off
REM Register: weekdays 07:55 paper trading, Saturday 10:00 weekly review
schtasks /create /tn "AI Trader daily" /tr "\"%~dp0run_trader.bat\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 07:55 /f
schtasks /create /tn "AI Trader weekly" /tr "\"%~dp0run_weekly.bat\"" /sc weekly /d SAT /st 10:00 /f
echo.
echo OK. Open Task Scheduler to check. Remove with the unregister file.
pause
