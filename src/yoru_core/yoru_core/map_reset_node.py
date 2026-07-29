"""Map reset listener (runs on the robot, started by real_robot.launch.py).

The dashboard's "Reset map" button publishes 'reset' on
/compliance/map_reset. This node deletes the robot's saved map files and
shuts the launch down cleanly after touching a restart flag;
start_robot.sh sees the flag, relaunches, and mode:=auto resolves to
mapping because the map is gone. The dashboard deletes the laptop's own
copy of the map before publishing.
"""

import glob
import os
import signal

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RESTART_FLAG = '/tmp/yoru_remap_restart'


class MapResetNode(Node):

    def __init__(self):
        super().__init__('map_reset_node')
        self.declare_parameter('maps_dir',
                               os.path.expanduser('~/Yoru_bot_V3/maps'))
        self.declare_parameter('map_name', 'main_map')
        self.create_subscription(String, '/compliance/map_reset',
                                 self.reset_callback, 10)
        self.get_logger().info('Map reset listener ready')

    def reset_callback(self, msg):
        if msg.data != 'reset':
            return
        maps_dir = self.get_parameter('maps_dir').value
        name = self.get_parameter('map_name').value
        removed = []
        for path in glob.glob(os.path.join(maps_dir, name + '.*')) + \
                glob.glob(os.path.join(maps_dir, name + '_serial.*')):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError as exc:
                self.get_logger().warn(f'Could not remove {path}: {exc}')
        self.get_logger().warn(
            f'MAP RESET: removed {removed if removed else "no files"}; '
            'restarting the launch into mapping mode')
        open(RESTART_FLAG, 'w').close()
        # Parent is the ros2 launch process; SIGINT = clean shutdown of
        # every node, then start_robot.sh relaunches (flag present).
        os.kill(os.getppid(), signal.SIGINT)


def main(args=None):
    rclpy.init(args=args)
    node = MapResetNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
