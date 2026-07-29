"""RPLIDAR A1 driver.

The serial port comes from the udev symlink installed by setup_pi.sh
(udev/99-yoru.rules), NOT from a USB by-path string. V2 hardcoded
    /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1:1.0-port0
which encodes the Raspberry Pi 4's PCIe controller address. The Pi 5 has a
different SoC and an RP1 southbridge, so that path does not exist there and
the node exits at startup. /dev/rplidar is stable across both boards and
across which USB port you happen to use.

Override if you have not installed the udev rules:
    ros2 launch yoru_base rplidar.launch.py serial_port:=/dev/ttyUSB0
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'serial_port', default_value='/dev/rplidar',
            description='udev symlink from udev/99-yoru.rules; '
                        'fall back to /dev/ttyUSB0 if not installed'),
        DeclareLaunchArgument('frame_id', default_value='laser_frame'),

        Node(
            package='rplidar_ros',
            executable='rplidar_composition',
            name='rplidar_node',
            output='screen',
            parameters=[{
                'serial_port': LaunchConfiguration('serial_port'),
                # RPLIDAR A1 runs at 115200; the driver default suits A2/A3
                'serial_baudrate': 115200,
                'frame_id': LaunchConfiguration('frame_id'),
                'angle_compensate': True,
                'scan_mode': 'Standard',
            }]
        )
    ])
