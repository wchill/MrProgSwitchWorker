#!/usr/bin/env bash

updaterepo() {
  repo=$1
  cd "$HOME/$repo" || exit
  git reset --hard HEAD
  git clean -fd
  git pull
  "$HOME/venv/bin/python" -m pip install -e "$HOME/$repo"
}

sudo systemctl stop trade-worker

updaterepo "BattleNetworkData"
updaterepo "BattleNetworkAutomation"
updaterepo "MrProgUtils"
updaterepo "MrProgSwitchWorker"

sudo systemctl start trade-worker
