#!/usr/bin/env bash
# SERVER (this laptop) - CCTV perception, PA announcements, escalation FSM,
# admin dashboard (auto-opens in the browser), incident log + Gmail email,
# admin joystick. The SAME command works for simulation and the real robot:
#
#   ./start_server.sh sim       # pair with ./start_sim.sh (other terminal)
#   ./start_server.sh           # pair with the real robot (./start_robot.sh on the Pi)
#   ./start_server.sh use_cctv2:=true   # extra args pass through to ros2 launch
set -e
cd "$(dirname "$0")"

source /opt/ros/jazzy/setup.bash
source ./ros_network.env
# Gmail app password etc. (git-ignored) - see secrets.env.example
[ -f secrets.env ] && source ./secrets.env

# The FastDDS discovery server lives on the robot (campus Wi-Fi blocks
# multicast). If the robot is off/unreachable, fall back to normal local
# discovery so the laptop still works standalone (sim, PA tests, etc.) -
# nodes on ONE machine never need the discovery server.
for a in "$@"; do
    if [ "$a" = "sim" ] || [ "$a" = "sim:=true" ]; then
        # Simulation pairing is fully local (start_sim.sh does the same)
        unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT
    fi
done
if [ -n "$ROS_DISCOVERY_SERVER" ]; then
    DS_HOST="${ROS_DISCOVERY_SERVER%%:*}"
    if ! ping -c 1 -W 1 "$DS_HOST" > /dev/null 2>&1; then
        echo "[yoru] robot ($DS_HOST) unreachable - STANDALONE mode"
        echo "[yoru] (start the robot first if you want the real robot connected)"
        unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT
    fi
fi

if [ ! -f install/setup.bash ]; then
    echo "First run: building workspace..."
    colcon build --symlink-install
fi
source install/setup.bash

# "./start_server.sh sim" is a friendly shortcut for sim:=true
ARGS=()
for a in "$@"; do
    if [ "$a" = "sim" ]; then ARGS+=("sim:=true"); else ARGS+=("$a"); fi
done

exec ros2 launch yoru_bringup server.launch.py "${ARGS[@]}"
