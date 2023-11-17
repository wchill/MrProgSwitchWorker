cd "$($env:UserProfile)\Desktop"
mkdir MrProg
cd MrProg
git clone https://github.com/wchill/BattleNetworkAutomation
git clone https://github.com/wchill/BattleNetworkData
git clone https://github.com/wchill/MrProgUtils
git clone https://github.com/wchill/MrProgWorker
python -m pip install virtualenv
python -m virtualenv venv
. venv/Scripts/activate.ps1

pip install -e BattleNetworkAutomation -e BattleNetworkData -e MrProgUtils -e MrProgWorker