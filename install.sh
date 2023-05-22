#!/usr/bin/env bash
DIR="$( dirname -- "${BASH_SOURCE[0]}"; )";   # Get the directory name
DIR="$( realpath -e -- "$DIR"; )";    # Resolve its full path if need be
AUTOMATION_SCRIPT_DIR="$DIR/BattleNetworkAutomation/src/nx/scripts"

appendfile() {
  line=$1
  f=$2
  echo "Adding '$line' to $f" && sudo bash -c "(grep -qxF \"$line\" $f || echo \"$line\" >> $f)"
}

sudo apt update
sudo apt install -y raspberrypi-bootloader raspberrypi-kernel raspberrypi-kernel-headers git build-essential vim python3-pip tesseract-ocr ffmpeg cmake lsb-release curl

read -p "Set current hostname to: " -r HOSTNAME
read -p "AMQP/MQTT host: " -r HOST
read -p "AMQP/MQTT username: " -r USERNAME
read -p "AMQP/MQTT password: " -r -s PASSWORD
read -p "Game: " -r GAME

sudo hostnamectl set-hostname "$HOSTNAME"

# install tailscale
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up

v4l2version=0.12.7
xpadversion=0.4
sudo rm -rf /usr/src/v4l2loopback-${v4l2version}
sudo git clone https://github.com/umlaeute/v4l2loopback.git /usr/src/v4l2loopback-${xpadversion}
sudo dkms remove -m v4l2loopback -v ${v4l2version} --all
sudo dkms add -m v4l2loopback -v ${v4l2version}
sudo dkms build -m v4l2loopback -v ${v4l2version}
sudo dkms install -m v4l2loopback -v ${v4l2version}
sudo rm -rf /usr/src/xpad-${xpadversion}
sudo git clone https://github.com/paroj/xpad.git /usr/src/xpad-${xpadversion}
sudo dkms remove -m xpad -v 0.4 --all
sudo dkms install -m xpad -v ${xpadversion}

sudo git clone https://github.com/mpromonet/v4l2rtspserver.git /usr/src/v4l2rtspserver
cd /usr/src/v4l2rtspserver || exit
sudo cmake . && sudo make -j 4 && sudo make install


# TODO: create virtualenv and stuff
if [[ ! -d "$DIR/venv" ]] ; then
  echo "Creating python virtualenv"
  python3 -m pip install virtualenv
  python3 -m virtualenv "$DIR/venv"
  git clone https://github.com/wchill/BattleNetworkData
  git clone https://github.com/wchill/BattleNetworkAutomation
  git clone https://github.com/wchill/MrProgUtils
  git clone https://github.com/wchill/MrProgSwitchWorker
  "$DIR/venv/bin/python" -m pip install -e "$DIR/BattleNetworkData"
  "$DIR/venv/bin/python" -m pip install -e "$DIR/BattleNetworkAutomation"
  "$DIR/venv/bin/python" -m pip install -e "$DIR/MrProgUtils"
  "$DIR/venv/bin/python" -m pip install -e "$DIR/MrProgSwitchWorker"
fi

echo "Writing udev rule for TC358743 HDMI module"
echo 'KERNEL=="video[0-9]*", SUBSYSTEM=="video4linux", KERNELS=="fe801000.csi|fe801000.csi1", ATTR{name}=="unicam-image", SYMLINK+="hdmi-capture", TAG+="systemd"' > /usr/lib/udev/rules.d/90-tc358743.rules

# Load the needed modules on boot
TEXT='dtoverlay=dwc2'
FILE='/boot/config.txt'
appendfile $TEXT $FILE

TEXT='dtoverlay=tc358743'
appendfile $TEXT $FILE

MODLOADFILE='/etc/modules-load.d/usbhid.conf'
echo "Writing modules-load.d conf to $MODLOADFILE"
cat << EOF | sudo tee $MODLOADFILE > /dev/null
dwc2
tc358743
libcomposite
v4l2loopback
xpad
EOF

MODFILE='/etc/modprobe.d/v4l2loopback.conf'
echo "Writing modprobe conf to $MODFILE"
cat << EOF | sudo tee $MODFILE > /dev/null
options v4l2loopback video_nr=100,101
options v4l2loopback card_label="Screen capture loopback"
EOF

# Create systemd service file
UNITFILE='/etc/systemd/system/tc358743.service'
echo "Writing tc358743 service file to $UNITFILE"
cat << EOF | sudo tee $UNITFILE > /dev/null
[Unit]
Description=EDID loader for TC358743
After=systemd-modules-load.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash $AUTOMATION_SCRIPT_DIR/init_tc358743.sh
ExecStop=/bin/true
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

UNITFILE='/etc/systemd/system/v4l2loopback.service'
echo "Writing v4l2loopback service file to $UNITFILE"
cat << EOF | sudo tee $UNITFILE > /dev/null
[Unit]
Description=V4L2 loopback feeder
After=tc358743.service

[Service]
Type=simple
ExecStart=/usr/bin/ffmpeg -f video4linux2 -input_format bgr24 -video_size 1280x720 -vsync 2 -i /dev/hdmi-capture -codec copy -f v4l2 /dev/video100 -filter:v fps=30 -codec h264_v4l2m2m -f v4l2 -b:v 3M -fflags nobuffer /dev/video101
Restart=always

[Install]
WantedBy=multi-user.target
EOF

UNITFILE='/etc/systemd/system/v4l2rtspserver.service'
echo "Writing v4l2rtspserver service file to $UNITFILE"
cat << EOF | sudo tee $UNITFILE > /dev/null
[Unit]
Description=V4L2 RTSP server
After=v4l2loopback.service

[Service]
Type=simple
ExecStart=v4l2rtspserver -S1 -f -Q 3 /dev/video101
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

UNITFILE='/etc/systemd/system/usb-gadget.service'
STARTUP_CMD="$DIR/venv/bin/python $AUTOMATION_SCRIPT_DIR/start_server.py"
echo "Writing usbgadget service file to $UNITFILE"
cat << EOF | sudo tee $UNITFILE > /dev/null
[Unit]
Description=USB gadget initialization
After=systemd-networkd-wait-online.service
Wants=systemd-networkd-wait-online.service
[Service]
Type=simple
ExecStart=$STARTUP_CMD
Restart=always
StandardOutput=journal+console
[Install]
WantedBy=sysinit.target
EOF

UNITFILE='/etc/systemd/system/trade-worker.service'
STARTUP_CMD="$DIR/venv/bin/python $DIR/MrProgSwitchWorker/src/mrprog/worker/trade_worker.py --host $HOST --username $USERNAME --password $PASSWORD --platform switch --game $GAME"
echo "Writing trade worker service file to $UNITFILE"
cat << EOF | sudo tee $UNITFILE > /dev/null
[Unit]
Description=Mr. Prog Switch Trade Worker
After=systemd-networkd-wait-online.service usb-gadget.service v4l2loopback.service
Wants=systemd-networkd-wait-online.service usb-gadget.service v4l2loopback.service
[Service]
Type=simple
ExecStart=$STARTUP_CMD
Restart=always
StandardOutput=journal+console
[Install]
WantedBy=sysinit.target
EOF
systemctl daemon-reload
systemctl enable usb-gadget
systemctl enable tc358743
systemctl enable v4l2loopback
systemctl enable v4l2rtspserver
systemctl enable trade-worker

echo "Setup done, you might need to reboot"
