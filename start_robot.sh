#!/usr/bin/env bash
# REAL ROBOT - run this ON the Raspberry Pi 5 (deployed with ./deploy_to_pi.sh).
# Runs: motors, RPLIDAR, Pi camera, robot speaker, SLAM/AMCL + Nav2 onboard.
# The laptop runs ./start_server.sh (both machines on the same Wi-Fi).
#
# Usage (on the Pi):
#   ./start_robot.sh                    # auto: mapping if no saved map yet,
#                                       #       localization once a map exists
#   ./start_robot.sh mode:=mapping      # force re-mapping
#   ./start_robot.sh camera:=usb        # USB webcam instead of the Pi camera
set -e
cd "$(dirname "$0")"

source /opt/ros/jazzy/setup.bash
source ./ros_network.env

# Ubuntu 24.04 enforces PEP 668, so pip packages that have no Debian package
# (piper-tts) live in a venv created by setup_pi.sh. Putting it on PYTHONPATH
# rather than activating it keeps the system rclpy/cv_bridge visible.
YORU_VENV="$HOME/yoru_venv"
if [ -d "$YORU_VENV" ]; then
    export PATH="$YORU_VENV/bin:$PATH"
    VENV_SITE=$(echo "$YORU_VENV"/lib/python3*/site-packages)
    export PYTHONPATH="$VENV_SITE:$PYTHONPATH"
fi

# Campus Wi-Fi blocks multicast: discovery runs through a FastDDS discovery
# server hosted here on the robot (see ros_network.env). Start it if it
# isn't already running; it stays up across launch restarts.
if ! pgrep -f "fastdds discovery" > /dev/null; then
    nohup fastdds discovery -i 0 -p 11811 > /tmp/fastdds_discovery.log 2>&1 &
    sleep 1
    echo "[yoru] started FastDDS discovery server on :11811"
fi

if [ ! -f install/setup.bash ]; then
    echo "First run: building workspace (this takes a while on the Pi)..."
    colcon build --symlink-install
fi
source install/setup.bash

# The dashboard's "Reset map" button makes map_reset_node delete the map,
# touch the flag and stop the launch - then we relaunch, and mode:=auto
# resolves to mapping because the map is gone.
while true; do
    ros2 launch yoru_bringup real_robot.launch.py "$@"
    if [ -f /tmp/yoru_remap_restart ]; then
        rm -f /tmp/yoru_remap_restart
        echo "[yoru] map reset - relaunching (no map -> mapping mode)"
        continue
    fi
    break
done
