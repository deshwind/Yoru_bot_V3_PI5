#!/usr/bin/env bash
# Deploy the workspace to the Raspberry Pi over SSH and build it there.
# Re-run after ANY code change AND after saving a new map in the dashboard
# (it syncs maps/ so the robot can localize on the new map).
#
# Usage:
#   ./deploy_to_pi.sh [pi-ip] [user]          # defaults below if omitted
#
# First time only, run on the Pi beforehand (this script copies it over):
#   ./setup_pi.sh
set -e
cd "$(dirname "$0")"

PI_IP="${1:-172.18.16.26}"     # default: this robot's Pi
PI_USER="${2:-desh}"
DEST="$PI_USER@$PI_IP"
REMOTE_WS="/home/$PI_USER/Yoru_bot_V3"

echo ">>> Checking SSH connection to $DEST ..."
ssh -o ConnectTimeout=5 "$DEST" 'echo "  connected: $(hostname) ($(uname -m))"'

echo ">>> Syncing workspace sources to $DEST:$REMOTE_WS ..."
rsync -az --delete --info=stats1 \
      --exclude build --exclude install --exclude log --exclude data \
      --exclude '*.pt' --exclude '__pycache__' \
      src maps udev ros_network.env start_robot.sh setup_pi.sh \
      "$DEST:$REMOTE_WS/"

echo ">>> Building on the Pi (first build can take ~10 min) ..."
ssh "$DEST" "source /opt/ros/jazzy/setup.bash && cd $REMOTE_WS && \
             colcon build --symlink-install 2>&1 | tail -3"

echo ">>> Done. On the Pi run:   cd $REMOTE_WS && ./start_robot.sh"
echo ">>> On this laptop run:    ./start_server.sh"
