"""slam_toolbox async online mapping - ROS 2 Jazzy.

WHY THIS FILE WAS REWRITTEN
---------------------------
In Jazzy, slam_toolbox's async_slam_toolbox_node is a **LifecycleNode**. It
starts in the 'unconfigured' state and does nothing at all until something
drives it through configure -> activate.

V2's vendored copy launched it as a plain launch_ros Node. On Jazzy that
still starts the process, so the logs look healthy and `ros2 node list`
shows slam_toolbox - but it never subscribes to /scan and never publishes
/map or the map->odom transform. The symptom is a robot that appears to
boot correctly and then simply never maps anything.

This file therefore follows upstream's lifecycle pattern: emit CONFIGURE,
then ACTIVATE on the configuring->inactive transition.

Kept from V2:
  - the launch argument is still named 'params_file' (upstream calls it
    'slam_params_file'), because sim.launch.py and real_robot.launch.py
    pass params_file; renaming it would silently fall back to defaults.
  - the default params file is yoru_base's tuned copy, not slam_toolbox's.
  - the HasNodeParams guard, which catches a params file that has been
    propagated in from a parent launch and contains no slam_toolbox block.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, EmitEvent, LogInfo,
                            RegisterEventHandler)
from launch.conditions import IfCondition, UnlessCondition
from launch.events import matches_action
from launch.substitutions import (AndSubstitution, LaunchConfiguration,
                                  NotSubstitution, PythonExpression)
from launch_ros.actions import LifecycleNode
from launch_ros.descriptions import ParameterFile
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition
from nav2_common.launch import HasNodeParams


def generate_launch_description():
    autostart = LaunchConfiguration('autostart')
    use_lifecycle_manager = LaunchConfiguration('use_lifecycle_manager')
    use_sim_time = LaunchConfiguration('use_sim_time')
    params_file = LaunchConfiguration('params_file')

    default_params_file = os.path.join(
        get_package_share_directory('yoru_base'),
        'config', 'mapper_params_online_async.yaml')

    declare_autostart_cmd = DeclareLaunchArgument(
        'autostart', default_value='true',
        description='Automatically configure and activate slam_toolbox. '
                    'Ignored when use_lifecycle_manager is true.')
    declare_use_lifecycle_manager = DeclareLaunchArgument(
        'use_lifecycle_manager', default_value='false',
        description='Let an external Nav2 lifecycle manager own the node '
                    '(enables the bond connection) instead of self-starting')
    declare_use_sim_time_argument = DeclareLaunchArgument(
        'use_sim_time', default_value='false',
        description='Use simulation/Gazebo clock')
    declare_params_file_cmd = DeclareLaunchArgument(
        'params_file', default_value=default_params_file,
        description='Full path to the ROS 2 parameters file for slam_toolbox')

    # If the params file handed down from a parent launch has no slam_toolbox
    # block, fall back to ours rather than starting with nothing.
    # https://github.com/ros-planning/navigation2/pull/2243#issuecomment-800479866
    has_node_params = HasNodeParams(source_file=params_file,
                                    node_name='slam_toolbox')

    actual_params_file = PythonExpression(
        ['"', params_file, '" if ', has_node_params,
         ' else "', default_params_file, '"'])

    log_param_change = LogInfo(
        msg=['provided params_file ', params_file,
             ' does not contain slam_toolbox parameters. Using default: ',
             default_params_file],
        condition=UnlessCondition(has_node_params))

    start_async_slam_toolbox_node = LifecycleNode(
        parameters=[
            ParameterFile(actual_params_file, allow_substs=True),
            {
                'use_lifecycle_manager': use_lifecycle_manager,
                'use_sim_time': use_sim_time,
            },
        ],
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        namespace='')

    # unconfigured -> inactive
    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(
                start_async_slam_toolbox_node),
            transition_id=Transition.TRANSITION_CONFIGURE),
        condition=IfCondition(
            AndSubstitution(autostart,
                            NotSubstitution(use_lifecycle_manager))))

    # inactive -> active (only once configuring has actually succeeded)
    activate_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=start_async_slam_toolbox_node,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                LogInfo(msg='[yoru] slam_toolbox configured, activating.'),
                EmitEvent(event=ChangeState(
                    lifecycle_node_matcher=matches_action(
                        start_async_slam_toolbox_node),
                    transition_id=Transition.TRANSITION_ACTIVATE)),
            ]),
        condition=IfCondition(
            AndSubstitution(autostart,
                            NotSubstitution(use_lifecycle_manager))))

    ld = LaunchDescription()
    ld.add_action(declare_autostart_cmd)
    ld.add_action(declare_use_lifecycle_manager)
    ld.add_action(declare_use_sim_time_argument)
    ld.add_action(declare_params_file_cmd)
    ld.add_action(log_param_change)
    ld.add_action(start_async_slam_toolbox_node)
    ld.add_action(configure_event)
    ld.add_action(activate_event)
    return ld
