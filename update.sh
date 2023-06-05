#!/usr/bin/env bash

updaterepo() {
  repo=$1
  cd "$HOME/$repo" || exit
  git clean -fd
  git fetch origin
  git reset --hard origin/master
  git pull
  "$HOME/venv/bin/python" -m pip install -e "$HOME/$repo"
}

sudo systemctl stop trade-worker
sudo systemctl stop usb-gadget

updaterepo "BattleNetworkData"
updaterepo "BattleNetworkAutomation"
updaterepo "MrProgUtils"
updaterepo "MrProgSwitchWorker"

sudo systemctl start usb-gadget
sudo systemctl start trade-worker
