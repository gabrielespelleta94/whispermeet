@echo off
rem WhisperMeet: instalador. Doble clic, o "instalar.bat --comprobar" para ver que falta sin cambiar nada.
rem Busca Python (el lanzador "py -3" o "python"), llama a instalar.py y deja la ventana abierta al terminar o si falla.
rem Cada candidato se PRUEBA (sin stdin ni salida) y se acepta solo si termina bien: el alias de la Tienda de Windows aparece al buscarlo en el PATH pero no ejecuta nada,
rem y un lanzador sin Python instalado podria quedarse esperando una respuesta.
setlocal
pushd "%~dp0"
set "PY="
py -3 -c "import sys" <nul >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys" <nul >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo No se encuentra Python en este equipo.
  echo Instala Python 3.12 o superior desde https://www.python.org/downloads/ y vuelve a ejecutar instalar.bat.
  set "COD=1"
  goto fin
)
%PY% instalar.py %*
set "COD=%ERRORLEVEL%"
if not "%COD%"=="0" (
  echo.
  echo El instalador ha terminado con avisos o errores: lee los mensajes de arriba.
)
:fin
echo.
pause
popd
exit /b %COD%
