@echo off
REM Windows py_compile check — 验证所有 Python 文件语法
REM Usage: scripts\check_syntax.bat

echo === EchoVault Syntax Check ===
echo.

set FAILED=0

python -m py_compile main.py
if %ERRORLEVEL% neq 0 set FAILED=1

for %%f in (core\*.py) do (
    python -m py_compile %%f
    if !ERRORLEVEL! neq 0 set FAILED=1
)

for %%f in (ui\*.py) do (
    python -m py_compile %%f
    if !ERRORLEVEL! neq 0 set FAILED=1
)

for %%f in (ui\views\*.py) do (
    python -m py_compile %%f
    if !ERRORLEVEL! neq 0 set FAILED=1
)

for %%f in (scripts\*.py) do (
    python -m py_compile %%f
    if !ERRORLEVEL! neq 0 set FAILED=1
)

echo.
if %FAILED%==0 (
    echo ALL FILES PASSED
) else (
    echo SOME FILES FAILED
)
