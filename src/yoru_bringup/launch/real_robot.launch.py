"""REAL ROBOT bring-up - run this ON the Raspberry Pi (Yoru V2).

    ros2 launch yoru_bringup real_robot.launch.py

Runs everything that must live on the robot:
  - robot description (TF tree)
  - L298N motor driver (PWM + encoders + PID + odometry)
  - RPLIDAR
  - robot camera (camera:=picam for the Pi Camera Module via camera_ros,
    camera:=usb for a USB webcam, camera:=none)
  - twist_mux (joystick > tracker > navigation priorities)
  - robot speaker (direct warning on arrival; the server speaks the PA)
  - SLAM or AMCL + Nav2 onboard, so the safety-critical motion loop keeps
    working even if Wi-Fi drops

First run (no saved map on the Pi): boots in MAPPING mode automatically -
drive from the dashboard Setup screen (keyboard) or the PS4 pad, press
Save Map in the dashboard, mark the camera spots, then run
./deploy_to_pi.sh again (syncs the map) and restart this launch.

The server half (CCTV perception, FSM, dashboard, email) runs
server.launch.py on the laptop. Both machines just need the same
ROS_DOMAIN_ID (see ros_network.env).

Arguments:
  mode   : auto (default) | mapping | localization
  map    : saved map yaml (default: ~/Yoru_bot_V3/maps/main_map.yaml)
  camera : picam (default) | usb | none
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, TimerAction)
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

DEFAULT_MAP = os.path.expanduser('~/Yoru_bot_V3/maps/main_map.yaml')


def resolve_mode(context):
    """mode:=auto -> mapping when no saved map exists, else localization."""
    mode = LaunchConfiguration('mode').perform(context)
    map_file = LaunchConfiguration('map').perform(context)
    if mode == 'auto':
        mode = 'localization' if os.path.isfile(map_file) else 'mapping'
        print(f'[yoru] mode:=auto resolved to "{mode}" '
              f'(map {"found" if mode == "localization" else "not found"}: '
              f'{map_file})')

    yoru_base_dir = get_package_share_directory('yoru_base')
    nav2_params = os.path.join(yoru_base_dir, 'config', 'nav2_params.yaml')
    if mode == 'mapping':
        include = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(yoru_base_dir, 'launch', 'online_async_launch.py')),
            launch_arguments={
                'use_sim_time': 'false',
                'params_file': os.path.join(yoru_base_dir, 'config',
                                            'mapper_params_online_async.yaml'),
            }.items())
    else:
        include = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(yoru_base_dir, 'launch', 'localization_launch.py')),
            launch_arguments={'map': map_file, 'use_sim_time': 'false',
                              'params_file': nav2_params}.items())
    return [TimerAction(period=3.0, actions=[include])]


def generate_launch_description():
    bringup_dir = get_package_share_directory('yoru_bringup')
    yoru_base_dir = get_package_share_directory('yoru_base')
    params_file = os.path.join(bringup_dir, 'config', 'yoru_real.yaml')
    nav2_params = os.path.join(yoru_base_dir, 'config', 'nav2_params.yaml')

    declare_args = [
        DeclareLaunchArgument('mode', default_value='auto',
                              description='auto | mapping | localization'),
        DeclareLaunchArgument('map', default_value=DEFAULT_MAP),
        DeclareLaunchArgument(
            'camera', default_value='picam',
            description='picam (Pi Camera Module via camera_ros) | usb | none'),
        DeclareLaunchArgument('use_nav2', default_value='true'),
    ]

    # Robot description without ros2_control (the L298N node drives motors)
    rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'rsp.launch.py')),
        launch_arguments={'use_sim_time': 'false',
                          'use_ros2_control': 'false'}.items())

    # Pi -> Arduino Nano Every (firmware/yoru_motor_bridge) -> L298N
    motor_driver = Node(
        package='yoru_core', executable='arduino_driver_node',
        parameters=[params_file], output='screen')

    lidar = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'rplidar.launch.py')))

    # Pi Camera Module (libcamera) - needs: sudo apt install ros-humble-camera-ros
    # format BGR888: the IMX477 otherwise auto-selects NV21, which the
    # JPEG compressor and cv_bridge cannot handle (empty/blank frames)
    camera_picam = Node(
        package='camera_ros', executable='camera_node', name='camera',
        parameters=[{'width': 640, 'height': 480, 'format': 'BGR888'}],
        remappings=[('/camera/camera_info', '/camera/camera_info'),
                    ('/camera/image_raw', '/camera/image_raw')],
        condition=LaunchConfigurationEquals('camera', 'picam'),
        output='screen')
    camera_usb = Node(
        package='yoru_core', executable='camera_publisher_node',
        parameters=[{'device': 0, 'fps': 5.0}],
        condition=LaunchConfigurationEquals('camera', 'usb'),
        output='screen')

    # twist_mux arbitrates joystick (100) > tracker/e-stop (20) > Nav2 (10)
    # and emits plain Twist on /cmd_vel_mux, which arduino_driver_node reads
    # directly. The hardware path never touches ros2_control, so Jazzy's
    # TwistStamped requirement does not apply here - only the sim needs the
    # twist_stamper_node adapter.
    twist_mux_params = os.path.join(yoru_base_dir, 'config', 'twist_mux.yaml')
    twist_mux = Node(
        package='twist_mux', executable='twist_mux',
        parameters=[twist_mux_params],
        remappings=[('/cmd_vel_out', '/cmd_vel_mux')])

    # The robot's speaker delivers the direct warning on arrival
    # (config section robot_audio_node: speak_pa false, speak_direct true)
    audio = Node(
        package='yoru_core', executable='audio_warning_node',
        name='robot_audio_node',
        parameters=[params_file], output='screen')

    # Dashboard "Reset map" -> delete the Pi's map + relaunch into mapping
    map_reset = Node(
        package='yoru_core', executable='map_reset_node',
        parameters=[{'maps_dir': os.path.dirname(DEFAULT_MAP),
                     'map_name': 'main_map'}],
        output='screen')

    slam_or_amcl = OpaqueFunction(function=resolve_mode)

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'navigation_launch.py')),
        launch_arguments={'use_sim_time': 'false',
                          'params_file': nav2_params}.items(),
        condition=IfCondition(LaunchConfiguration('use_nav2')))

    return LaunchDescription(declare_args + [
        rsp,
        motor_driver,
        lidar,
        camera_picam,
        camera_usb,
        twist_mux,
        audio,
        map_reset,
        slam_or_amcl,
        TimerAction(period=6.0, actions=[nav2]),
    ])
