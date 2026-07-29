"""ONE-COMMAND simulation: robot + server together (Yoru V2).

    ./start_sim.sh          (which runs: ros2 launch yoru_bringup sim_full.launch.py)

Combines the two halves in a single process:
  - sim.launch.py    : Gazebo two-room world + robot + SLAM/AMCL + Nav2 + RViz
  - server.launch.py : CCTV perception + PA voice + FSM + dashboard (sim:=true)

This is exactly equivalent to running ./start_sim.sh robot and
./start_server.sh sim in two terminals - use those when you want the
server logs separated (e.g. mirroring the real laptop + Pi deployment).

Arguments (all forwarded):
  mode         : auto (default) | mapping | localization
  map          : saved map yaml (default: ~/Yoru_bot_V3/maps/main_map.yaml)
  gui / rviz   : Gazebo GUI / RViz (default: true)
  open_browser : auto-open the dashboard (default: true)
  use_joystick : PS4 admin joystick (default: true)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

DEFAULT_MAP = os.path.expanduser('~/Yoru_bot_V3/maps/main_map.yaml')


def generate_launch_description():
    launch_dir = os.path.join(
        get_package_share_directory('yoru_bringup'), 'launch')

    declare_args = [
        DeclareLaunchArgument('mode', default_value='auto',
                              description='auto | mapping | localization'),
        DeclareLaunchArgument('map', default_value=DEFAULT_MAP),
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('open_browser', default_value='true'),
        DeclareLaunchArgument('use_joystick', default_value='true'),
    ]

    sim_args = {
        'mode': LaunchConfiguration('mode'),
        'map': LaunchConfiguration('map'),
        'gui': LaunchConfiguration('gui'),
        'rviz': LaunchConfiguration('rviz'),
    }
    robot_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'sim.launch.py')),
        launch_arguments=sim_args.items())

    server = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'server.launch.py')),
        launch_arguments={
            'sim': 'true',
            'open_browser': LaunchConfiguration('open_browser'),
            'use_joystick': LaunchConfiguration('use_joystick'),
        }.items())

    return LaunchDescription(declare_args + [robot_sim, server])
