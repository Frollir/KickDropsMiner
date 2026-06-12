@echo off
IF NOT EXIST 7z.exe GOTO NO7Z
IF NOT EXIST "Kick Drops Miner" mkdir "Kick Drops Miner"
rem Prepare files
copy /y /v dist\*.exe "Kick Drops Miner"
copy /y /v manual.txt "Kick Drops Miner"
IF EXIST "Kick Drops Miner.zip" (
    rem Add action
    set action=a
) ELSE (
    rem Update action
    set action=u
)
rem Pack and test
7z %action% "Kick Drops Miner.zip" "Kick Drops Miner/" -r
7z t "Kick Drops Miner.zip" * -r
rem Cleanup
IF EXIST "Kick Drops Miner" rmdir /s /q "Kick Drops Miner"
GOTO EXIT
:NO7Z
echo No 7z.exe detected, skipping packaging!
GOTO EXIT
:EXIT
exit %errorlevel%
