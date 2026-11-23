@echo off
REM Weekdays 07:55 paper trading + Saturday 10:00 weekly review.
REM WakeToRun: wakes the PC from sleep (not from shutdown). StartWhenAvailable: runs late if PC was off at 07:55.
set "D=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 10); $a=New-ScheduledTaskAction -Execute ($env:D + 'run_trader.bat'); $t=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 07:55; Register-ScheduledTask -TaskName 'AI Trader daily' -Action $a -Trigger $t -Settings $s -Force | Out-Null; $a2=New-ScheduledTaskAction -Execute ($env:D + 'run_weekly.bat'); $t2=New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At 10:00; Register-ScheduledTask -TaskName 'AI Trader weekly' -Action $a2 -Trigger $t2 -Settings $s -Force | Out-Null; Write-Host 'OK: AI Trader daily (Mon-Fri 07:55), AI Trader weekly (Sat 10:00)'"
echo.
echo Keep the PC on or in SLEEP (not shut down). Enable "wake timers" in Power Options.
pause
