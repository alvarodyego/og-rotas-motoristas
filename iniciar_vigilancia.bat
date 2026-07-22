@echo off
REM Duplo-clique neste arquivo para ligar a vigilancia automatica.
REM Ele fica rodando, olhando a pasta do Google Drive, e publica sozinho
REM no GitHub Pages sempre que um novo relatorio do PathFind aparecer.
REM Feche esta janela para parar a vigilancia.

set /p PASTA_DRIVE="Cole aqui o caminho da pasta do Google Drive e pressione Enter: "

cd /d "%~dp0"
python watch_and_publish.py "%PASTA_DRIVE%"
pause
