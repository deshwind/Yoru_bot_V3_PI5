"""Arduino motor bridge node for the real robot.

HARDWARE-ONLY node: talks to the Nano Every running
firmware/yoru_motor_bridge (a ROSArduinoBridge port) over USB serial.
The Arduino does PWM + encoder counting + onboard PID at 30 Hz; this
node does the differential-drive kinematics and wheel odometry
(odom -> base_link TF), so it is a drop-in replacement for the GPIO
l298n_driver_node with the same topic contract.

Subscribes the twist_mux output (default /cmd_vel_mux) as plain Twist.

This node bypasses ros2_control entirely, so Jazzy's move to a
TwistStamped-only diff_drive_controller does not affect the hardware path -
only the simulation needs yoru_core/twist_stamper_node to adapt.

Protocol (57600 baud, CR-terminated, request/response):
  m <l> <r>  closed-loop wheel speeds in encoder counts per 33 ms frame
  e          -> "left right" encoder counts
  r          reset encoder counts
  u kp:kd:ki:ko  update onboard PID gains
Firmware auto-stops the motors if no m/o command arrives for 2 s.
"""

import math
import time

import rclpy
import serial
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import TransformBroadcaster

FIRMWARE_PID_RATE = 30.0  # Hz, fixed in yoru_motor_bridge.ino


class ArduinoDriverNode(Node):

    def __init__(self):
        super().__init__('arduino_driver_node')

        # udev symlink from udev/99-yoru.rules; /dev/ttyACM0 also works but
        # is not stable if anything else enumerates first.
        self.declare_parameter('serial_port', '/dev/arduino')
        self.declare_parameter('baud_rate', 57600)
        # measured 2026-07-07 by hand-rotating the wheels one revolution
        self.declare_parameter('enc_counts_per_rev', 1320)
        self.declare_parameter('wheel_radius', 0.0435)
        self.declare_parameter('wheel_separation', 0.32)
        self.declare_parameter('max_wheel_speed', 0.3)  # m/s clamp
        # onboard PID gains (integers, output = (Kp*err + ...)/Ko)
        self.declare_parameter('kp', 20)
        self.declare_parameter('kd', 12)
        self.declare_parameter('ki', 0)
        self.declare_parameter('ko', 50)
        self.declare_parameter('cmd_vel_topic', '/cmd_vel_mux')
        self.declare_parameter('cmd_timeout', 0.5)
        self.declare_parameter('loop_rate', 20.0)  # Hz, serial + odometry

        port = self.get_parameter('serial_port').value
        baud = int(self.get_parameter('baud_rate').value)
        try:
            self.serial = serial.Serial(port, baud, timeout=0.5)
        except serial.SerialException as exc:
            self.get_logger().fatal(f'Cannot open {port}: {exc}')
            raise SystemExit(1)
        time.sleep(2.5)  # board resets when the port opens
        self.serial.reset_input_buffer()

        if self._command('b') != str(baud):
            self.get_logger().fatal(
                f'No yoru_motor_bridge firmware answering on {port} '
                f'(expected "{baud}" to the b command)')
            raise SystemExit(1)
        kp, kd, ki, ko = (int(self.get_parameter(n).value)
                          for n in ('kp', 'kd', 'ki', 'ko'))
        self._command(f'u {kp}:{kd}:{ki}:{ko}')
        self._command('r')

        self.target_left = 0.0   # wheel surface speed, m/s
        self.target_right = 0.0
        self.last_cmd_time = self.get_clock().now()
        self.prev_left_ticks = 0
        self.prev_right_ticks = 0
        self.prev_loop_time = self.get_clock().now()
        self.x = self.y = self.theta = 0.0

        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.create_subscription(Twist, self.get_parameter('cmd_vel_topic').value,
                                 self.cmd_callback, 10)
        period = 1.0 / self.get_parameter('loop_rate').value
        self.create_timer(period, self.control_loop)

        self.get_logger().info(
            f'Arduino motor bridge ready on {port} '
            f'({self.get_parameter("enc_counts_per_rev").value} counts/rev)')

    def _command(self, cmd):
        """Send one command and return the single-line reply (or '')."""
        self.serial.write((cmd + '\r').encode())
        return self.serial.readline().decode(errors='replace').strip()

    def cmd_callback(self, msg):
        half_l = self.get_parameter('wheel_separation').value / 2.0
        self.target_left = msg.linear.x - msg.angular.z * half_l
        self.target_right = msg.linear.x + msg.angular.z * half_l
        self.last_cmd_time = self.get_clock().now()

    def control_loop(self):
        now = self.get_clock().now()
        dt = (now - self.prev_loop_time).nanoseconds * 1e-9
        self.prev_loop_time = now
        if dt <= 0.0:
            return
        if (now - self.last_cmd_time).nanoseconds * 1e-9 > \
                self.get_parameter('cmd_timeout').value:
            self.target_left = self.target_right = 0.0

        radius = self.get_parameter('wheel_radius').value
        cpr = self.get_parameter('enc_counts_per_rev').value
        max_speed = self.get_parameter('max_wheel_speed').value
        counts_per_meter = cpr / (2.0 * math.pi * radius)

        def to_frame_counts(v):
            v = max(-max_speed, min(max_speed, v))
            return int(round(v * counts_per_meter / FIRMWARE_PID_RATE))

        self._command(
            f'm {to_frame_counts(self.target_left)} '
            f'{to_frame_counts(self.target_right)}')

        reply = self._command('e')
        try:
            left_ticks, right_ticks = (int(v) for v in reply.split())
        except ValueError:
            # A timed-out read shifts every later reply by one command;
            # flush the buffer so the next cycle starts back in sync.
            self.get_logger().warn(f'Bad encoder reply: {reply!r}; resyncing')
            self.serial.reset_input_buffer()
            return

        d_left = (left_ticks - self.prev_left_ticks) / counts_per_meter
        d_right = (right_ticks - self.prev_right_ticks) / counts_per_meter
        self.prev_left_ticks = left_ticks
        self.prev_right_ticks = right_ticks

        # Odometry integration (differential drive kinematics)
        d_center = (d_left + d_right) / 2.0
        d_theta = (d_right - d_left) / self.get_parameter('wheel_separation').value
        self.x += d_center * math.cos(self.theta + d_theta / 2.0)
        self.y += d_center * math.sin(self.theta + d_theta / 2.0)
        self.theta = math.atan2(math.sin(self.theta + d_theta),
                                math.cos(self.theta + d_theta))
        self.publish_odometry(now, d_center / dt, d_theta / dt)

    def publish_odometry(self, now, v, w):
        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = 'odom'
        odom.child_frame_id = 'base_link'
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation.z = math.sin(self.theta / 2.0)
        odom.pose.pose.orientation.w = math.cos(self.theta / 2.0)
        odom.twist.twist.linear.x = v
        odom.twist.twist.angular.z = w
        self.odom_pub.publish(odom)

        tf = TransformStamped()
        tf.header = odom.header
        tf.child_frame_id = 'base_link'
        tf.transform.translation.x = self.x
        tf.transform.translation.y = self.y
        tf.transform.rotation = odom.pose.pose.orientation
        self.tf_broadcaster.sendTransform(tf)

    def destroy_node(self):
        try:
            self._command('m 0 0')
            self.serial.close()
        except Exception:  # noqa: BLE001
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ArduinoDriverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
