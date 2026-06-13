@echo off
echo ==============================================
echo Building SpikeGuard SNN Engine C++ DLL...
echo ==============================================

if not exist src\inference (
    echo Error: src\inference directory not found.
    exit /b 1
)

g++ -O3 -shared -static -static-libgcc -static-libstdc++ -o snn_engine.dll src\inference\snn_engine.cpp

if %errorlevel% neq 0 (
    echo [ERROR] Compilation failed. See errors above.
    exit /b %errorlevel%
)

echo [SUCCESS] snn_engine.dll built successfully!
dir snn_engine.dll
