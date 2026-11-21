@echo off
REM Quick test script for Windows
REM Double-click this file to run all tests

echo.
echo ================================================================================
echo                     RUNNING PRE-SUBMISSION TESTS
echo ================================================================================
echo.

cd /d "%~dp0"

echo Running test script...
echo.

python test_before_submission.py

echo.
echo ================================================================================
echo                              TEST COMPLETE
echo ================================================================================
echo.
echo Press any key to exit...
pause > nul
