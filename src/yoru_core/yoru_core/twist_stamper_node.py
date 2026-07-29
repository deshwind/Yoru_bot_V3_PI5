"""Twist -> TwistStamped adapter for ros2_control on Jazzy.

WHY THIS EXISTS
---------------
ROS 2 Jazzy's diff_drive_controller subscribes to ~/cmd_vel as
geometry_msgs/TwistStamped. The Humble-era escape hatches are gone:
`use_stamped_vel` was removed as a parameter and the ~/cmd_vel_unstamped
topic no longer exists. See
https://control.ros.org/jazzy/doc/ros2_controllers/diff_drive_controller/doc/userdoc.html

Everything upstream of the controller still speaks plain Twist:
  - Nav2 (enable_stamped_cmd_vel defaults to false in Jazzy)
  - the dashboard's keyboard teleop        -> cmd_vel_tracker
  - the FSM's emergency stop               -> cmd_vel_tracker
  - teleop_twist_joy                       -> cmd_vel_joy
  - twist_mux, which arbitrates between them

Rather than restamp all of those, the whole priority chain stays on Twist
and one conversion happens at the very last hop, here.

This node runs in SIMULATION ONLY. On the real robot the twist_mux output
goes straight into arduino_driver_node, which reads Twist directly - the
hardware path never touches ros2_control, so it needs no conversion and
carries no regression risk from this change.

Topics:
  sub  cmd_vel_in   geometry_msgs/Twist
  pub  cmd_vel_out  geometry_msgs/TwistStamped
"""

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from rclpy.node import Node


class TwistStamperNode(Node):

    def __init__(self):
        super().__init__('twist_stamper_node')

        # base_link matches diff_drive_controller's base_frame_id. The
        # controller only reads linear.x and angular.z, but a correct frame
        # keeps rqt/rosbag inspection honest.
        self.declare_parameter('frame_id', 'base_link')
        self.frame_id = self.get_parameter('frame_id').value

        self.pub = self.create_publisher(TwistStamped, 'cmd_vel_out', 10)
        self.create_subscription(Twist, 'cmd_vel_in', self.callback, 10)

        self.get_logger().info(
            f'Twist -> TwistStamped adapter ready (frame_id: {self.frame_id})')

    def callback(self, msg):
        stamped = TwistStamped()
        # get_clock() honours use_sim_time, so the stamp follows Gazebo's
        # /clock in simulation. A wall-clock stamp here would sit far in the
        # future relative to sim time and the controller would discard it.
        stamped.header.stamp = self.get_clock().now().to_msg()
        stamped.header.frame_id = self.frame_id
        stamped.twist = msg
        self.pub.publish(stamped)


def main(args=None):
    rclpy.init(args=args)
    node = TwistStamperNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
