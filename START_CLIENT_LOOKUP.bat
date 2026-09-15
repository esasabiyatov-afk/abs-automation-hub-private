@echo off
setlocal
title Tolubay Client Lookup

set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\python.exe"

if not exist "%PYTHON%" set "PYTHON=%USERPROFILE%\Documents\Python_portable\python.exe"
if not exist "%PYTHON%" (
    echo.
    echo ERROR: portable Python not found.
    echo Expected: %%USERPROFILE%%\Documents\Python_portable\python.exe
    echo.
    pause
    exit /b 1
)

if not exist "%APP_DIR%client_lookup.py" (
    echo.
    echo ERROR: client_lookup.py is not located next to this BAT file.
    echo Extract the complete ZIP archive and keep the src folder.
    echo.
    pause
    exit /b 1
)

if not exist "%APP_DIR%src\automation_hub\tolubay.py" (
    echo.
    echo ERROR: src\automation_hub\tolubay.py was not found.
    echo Extract the complete ZIP archive, not only this BAT file.
    echo.
    pause
    exit /b 1
)

:choose_mode
cls
echo ============================================================
echo              POISK KLIENTOV TOLUBAY - READ ONLY
echo ============================================================
echo.
echo 1 - Poisk po INN
echo 2 - Poisk po FIO
echo 3 - Poisk po nazvaniyu yuridicheskogo litsa / OSOO
echo 0 - Vyhod
echo.
set "MODE="
set /p "MODE=Vyberite deystvie: "

if "%MODE%"=="0" exit /b 0
if "%MODE%"=="1" goto search_inn
if "%MODE%"=="2" goto search_fio
if "%MODE%"=="3" goto search_company
echo.
echo Vvedite 1, 2, 3 ili 0.
pause
goto choose_mode

:search_inn
echo.
set "QUERY="
set /p "QUERY=Vvedite INN klienta: "
if not defined QUERY (
    echo INN ne vveden.
    pause
    goto choose_mode
)
set "SEARCH_ARG=--inn"
goto run_search

:search_fio
echo.
set "QUERY="
set /p "QUERY=Vvedite FIO: Familiya Imya Otchestvo: "
if not defined QUERY (
    echo FIO ne vvedeno.
    pause
    goto choose_mode
)
set "SEARCH_ARG=--fio"
goto run_search

:search_company
echo.
set "QUERY="
set /p "QUERY=Vvedite nazvanie yuridicheskogo litsa ili OSOO: "
if not defined QUERY (
    echo Nazvanie ne vvedeno.
    pause
    goto choose_mode
)
set "SEARCH_ARG=--company"
goto run_search

:run_search
echo.
echo Programma zaprosit login i parol ABS.
echo Parol ne otobrazhaetsya i ne sohranyaetsya.
echo TLS-sertifikat dlya ob.tolubay.kg ne proveriaetsya.
echo Rezultat budet pokazan tolko na ekrane.
echo.

"%PYTHON%" -X utf8 "%APP_DIR%client_lookup.py" %SEARCH_ARG% "%QUERY%" --insecure
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo Poisk zavershilsya s oshibkoy. Kod: %EXIT_CODE%
    echo Dannye ne byli izmeneny.
) else (
    echo ============================================================
    echo GOTOVO. Rezultat pokazan na ekrane.
    echo ============================================================
)
echo.
pause
goto choose_mode
