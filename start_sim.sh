#!/usr/bin/env bash
# ONE COMMAND to run the whole simulation:
#   Gazebo (two-room world) + SLAM/AMCL + Nav2 + RViz
#   + CCTV smoking detection + PA voice + escalation FSM
#   + admin dashboard (auto-opens in the browser).
#
# Usage:
#   ./start_sim.sh                    # everything (auto: mapping if no map yet)
#   ./start_sim.sh mode:=mapping      # force re-mapping
#   ./start_sim.sh gui:=false rviz:=false
#
#   ./start_sim.sh robot              # robot side ONLY - then run
#                                     # ./start_server.sh sim in another
#                                     # terminal (mirrors the real deployment)
set -e
cd "$(dirname "$0")"

source /opt/ros/jazzy/setup.bash
source ./ros_network.env
# Gmail app password etc. (git-ignored) - see secrets.env.example
[ -f secrets.env ] && source ./secrets.env

# Simulation is fully local: never route discovery through the robot's
# FastDDS discovery server (it may be off, and sim doesn't need it).
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT

# Build once if the workspace has not been built yet
if [ ! -f install/setup.bash ]; then
    echo "First run: building workspace..."
    colcon build --symlink-install
fi
source install/setup.bash

if [ "$1" = "robot" ]; then
    shift
    echo ""
    echo "============================================================"
    echo "  Yoru V3 simulation (robot side only)"
    echo "  Now run the server in ANOTHER terminal:  ./start_server.sh sim"
    echo "============================================================"
    echo ""
    exec ros2 launch yoru_bringup sim.launch.py "$@"
fi

exec ros2 launch yoru_bringup sim_full.launch.py "$@"
