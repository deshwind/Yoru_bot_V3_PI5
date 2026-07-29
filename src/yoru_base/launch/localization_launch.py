# Copyright (c) 2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# PORTED TO ROS 2 JAZZY.
#
# use_sim_time is applied with SetParameter inside a GroupAction rather than
# rewritten into the params file. This matters, and the reason is subtle:
#
# nav2_params.yaml no longer carries use_sim_time keys. RewrittenYaml can
# insert missing keys, but its add_params() only does so for FULLY QUALIFIED
# paths - it requires 'ros__parameters' to appear in the dotted path:
#
#     yaml_keys = path.split('.')
#     if 'ros__parameters' in yaml_keys:
#         yaml = self.updateYamlPathVals(yaml, yaml_keys, new_val)
#
# V2 passed the bare leaf key 'use_sim_time', which has no such path. With
# the key gone from the YAML there is nothing to substitute and nothing gets
# added, so the rewrite silently becomes a no-op. AMCL would then run on
# wall-clock time in simulation while Gazebo published /clock, and
# localisation would drift immediately for no visible reason.
#
# yaml_filename is likewise passed as a direct parameter instead of a
# rewrite, matching upstream Jazzy.
#
# yaml_filename is likewise passed as a direct parameter instead of a
# rewrite, matching upstream Jazzy.

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, GroupAction,
                            SetEnvironmentVariable)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    # Get the launch directory
    bringup_dir = get_package_share_directory('yoru_base')

    namespace = LaunchConfiguration('namespace')
    map_yaml_file = LaunchConfiguration('map')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    params_file = LaunchConfiguration('params_file')
    lifecycle_nodes = ['map_server', 'amcl']

    # Map fully qualified names to relative ones so the node's namespace can be prepended.
    # In case of the transforms (tf), currently, there doesn't seem to be a better alternative
    # https://github.com/ros/geometry2/issues/32
    # https://github.com/ros/robot_state_publisher/pull/30
    # TODO(orduno) Substitute with `PushNodeRemapping`
    #              https://github.com/ros2/launch_ros/issues/56
    remappings = [('/tf', 'tf'),
                  ('/tf_static', 'tf_static')]

    # Nothing is rewritten any more: use_sim_time comes from SetParameter and
    # yaml_filename is passed straight to map_server below. RewrittenYaml is
    # kept so a namespace root_key still works.
    param_substitutions = {}

    configured_params = RewrittenYaml(
        source_file=params_file,
        root_key=namespace,
        param_rewrites=param_substitutions,
        convert_types=True)

    return LaunchDescription([
        # Set env var to print messages to stdout immediately
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),

        DeclareLaunchArgument(
            'namespace', default_value='',
            description='Top-level namespace'),

        DeclareLaunchArgument(
            'map',
            default_value=os.path.join(bringup_dir, 'maps', 'turtlebot3_world.yaml'),
            description='Full path to map yaml file to load'),

        DeclareLaunchArgument(
            'use_sim_time', default_value='false',
            description='Use simulation (Gazebo) clock if true'),

        DeclareLaunchArgument(
            'autostart', default_value='true',
            description='Automatically startup the nav2 stack'),

        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(bringup_dir, 'config', 'nav2_params.yaml'),
            description='Full path to the ROS2 parameters file to use'),

        GroupAction(actions=[
            SetParameter('use_sim_time', use_sim_time),

            Node(
                package='nav2_map_server',
                executable='map_server',
                name='map_server',
                output='screen',
                parameters=[configured_params,
                            {'yaml_filename': map_yaml_file}],
                remappings=remappings),

            Node(
                package='nav2_amcl',
                executable='amcl',
                name='amcl',
                output='screen',
                parameters=[configured_params],
                remappings=remappings),

            Node(
                package='nav2_lifecycle_manager',
                executable='lifecycle_manager',
                name='lifecycle_manager_localization',
                output='screen',
                parameters=[{'autostart': autostart},
                            {'node_names': lifecycle_nodes},
                            # Same bond hardening as navigation_launch.py:
                            # discovery over the FastDDS discovery server on
                            # the Pi is slow enough that the default 4s bond
                            # timeout intermittently aborts bringup.
                            {'bond_timeout': 60.0},
                            {'attempt_respawn_reconnection': True},
                            {'bond_respawn_max_duration': 30.0}]),
        ]),
    ])
