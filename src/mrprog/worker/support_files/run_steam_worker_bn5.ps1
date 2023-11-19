cd "$($env:UserProfile)\Desktop\MrProg"
. "venv\Scripts\activate.ps1"
python "MrProgWorker\src\mrprog\worker\trade_worker.py" --host bn-orchestrator --platform steam --game 5