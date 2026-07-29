"""L298N motor driver node for the real robot (dissertation Section 3.3).

LEGACY / REFERENCE IMPLEMENTATION. The supported motor path is
arduino_driver_node: the Pi talks to an Arduino Nano Every over USB serial
and the Arduino does PWM, quadrature counting and a 30 Hz PID onboard. This
node is kept because it documents the direct-GPIO approach.

HARDWARE-ONLY node: requires lgpio on a Raspberry Pi. In simulation the
robot is driven by gz_ros2_control instead.

PORTED FROM RPi.GPIO TO lgpio FOR THE RASPBERRY PI 5
----------------------------------------------------
RPi.GPIO cannot work on a Pi 5. It drives the GPIO by mapping the SoC's
peripheral registers through /dev/mem, but on the Pi 5 the header GPIOs
belong to the RP1 southbridge, not the SoC - so those registers are simply
not there. On Ubuntu it is doubly wrong: Ubuntu expects the kernel
character-device interface (/dev/gpiochipN) that lgpio uses.

Two caveats worth knowing before trusting this node on a Pi 5:

  1. lgpio's PWM is SOFTWARE timed. Under Ubuntu (no realtime kernel) the
     duty cycle jitters with system load, so the wheels will not hold speed
     as evenly as the Arduino's hardware PWM.
  2. Encoder edges are delivered as userspace callbacks. At any real wheel
     speed the Pi will MISS counts under load, and missed counts corrupt
     odometry silently - the robot believes it travelled less than it did.

Both are the reason the Arduino bridge exists and is the default.

  - PWM speed control on ENA/ENB at 1 kHz, direction via IN1-IN4
  - quadrature encoder feedback on interrupt-driven GPIO
  - per-wheel PID velocity control at 50 Hz with anti-windup
  - differential drive kinematics + wheel odometry (odom -> base_link TF)

Subscribes the twist_mux output (default /cmd_vel_mux) as plain Twist, the
same contract as arduino_driver_node.
"""

import math

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


class Pid:
    def __init__(self, kp, ki, kd, out_limit):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_limit = out_limit
        self.integral = 0.0
        self.prev_error = 0.0

    def step(self, error, dt):
        derivative = (error - self.prev_error) / dt if dt > 0 else 0.0
        self.prev_error = error
        out = self.kp * error + self.ki * self.integral + self.kd * derivative
        if -self.out_limit < out < self.out_limit:
            self.integral += error * dt  # anti-windup: freeze when saturated
        return max(-self.out_limit, min(self.out_limit, out))


class L298nDriverNode(Node):

    def __init__(self):
        super().__init__('l298n_driver_node')

        # BCM pin numbers - adjust to your wiring
        self.declare_parameter('ena_pin', 12)
        self.declare_parameter('in1_pin', 5)
        self.declare_parameter('in2_pin', 6)
        self.declare_parameter('enb_pin', 13)
        self.declare_parameter('in3_pin', 20)
        self.declare_parameter('in4_pin', 21)
        self.declare_parameter('left_encoder_pin', 17)
        self.declare_parameter('right_encoder_pin', 27)
        self.declare_parameter('pwm_frequency', 1000)
        self.declare_parameter('encoder_ticks_per_rev', 40)
        self.declare_parameter('wheel_radius', 0.033)
        self.declare_parameter('wheel_separation', 0.297)
        self.declare_parameter('max_wheel_speed', 0.3)  # m/s at 100% duty
        self.declare_parameter('kp', 2.0)
        self.declare_parameter('ki', 0.1)
        self.declare_parameter('kd', 0.5)
        self.declare_parameter('cmd_vel_topic', '/cmd_vel_mux')
        self.declare_parameter('cmd_timeout', 0.5)

        # -1 = autodetect the header's gpiochip. The RP1 on a Pi 5 is
        # normally gpiochip0, but older Pi 5 kernels exposed it as
        # gpiochip4, and getting this wrong drives the wrong pins.
        self.declare_parameter('gpiochip', -1)

        try:
            import lgpio
        except ImportError:
            self.get_logger().fatal(
                'lgpio not available. This node only runs on a Raspberry Pi '
                '(sudo apt install python3-lgpio). Note that RPi.GPIO is NOT '
                'a substitute on the Pi 5: its GPIO lives on the RP1 '
                'southbridge, which RPi.GPIO cannot reach. In simulation the '
                'robot is driven by gz_ros2_control.')
            raise SystemExit(1)
        self.lgpio = lgpio

        chip = int(self.get_parameter('gpiochip').value)
        if chip < 0:
            chip = self._detect_gpiochip()
        self.handle = lgpio.gpiochip_open(chip)
        self.get_logger().info(f'Opened /dev/gpiochip{chip}')

        p = {n: int(self.get_parameter(n).value) for n in
             ('ena_pin', 'in1_pin', 'in2_pin', 'enb_pin', 'in3_pin', 'in4_pin')}
        for pin in p.values():
            lgpio.gpio_claim_output(self.handle, pin, 0)
        self.pins = p
        self.pwm_freq = int(self.get_parameter('pwm_frequency').value)
        # lgpio has no persistent PWM object: tx_pwm() is called with the new
        # duty each time, so _set_motor drives it directly.
        lgpio.tx_pwm(self.handle, p['ena_pin'], self.pwm_freq, 0)
        lgpio.tx_pwm(self.handle, p['enb_pin'], self.pwm_freq, 0)

        self.left_ticks = 0
        self.right_ticks = 0
        self.left_dir = 1
        self.right_dir = 1
        le = int(self.get_parameter('left_encoder_pin').value)
        re = int(self.get_parameter('right_encoder_pin').value)
        # claim_alert (not claim_input) is what enables edge callbacks
        lgpio.gpio_claim_alert(self.handle, le, lgpio.BOTH_EDGES,
                               lFlags=lgpio.SET_PULL_UP)
        lgpio.gpio_claim_alert(self.handle, re, lgpio.BOTH_EDGES,
                               lFlags=lgpio.SET_PULL_UP)
        # Keep references: lgpio cancels a callback that gets garbage collected
        self._left_cb = lgpio.callback(self.handle, le, lgpio.BOTH_EDGES,
                                       self._left_tick)
        self._right_cb = lgpio.callback(self.handle, re, lgpio.BOTH_EDGES,
                                        self._right_tick)

        kp = self.get_parameter('kp').value
        ki = self.get_parameter('ki').value
        kd = self.get_parameter('kd').value
        self.pid_left = Pid(kp, ki, kd, 100.0)
        self.pid_right = Pid(kp, ki, kd, 100.0)

        self.target_left = 0.0   # wheel surface speed, m/s
        self.target_right = 0.0
        self.last_cmd_time = self.get_clock().now()
        self.prev_left_ticks = 0
        self.prev_right_ticks = 0
        self.x = self.y = self.theta = 0.0

        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.create_subscription(Twist, self.get_parameter('cmd_vel_topic').value,
                                 self.cmd_callback, 10)
        self.create_timer(0.02, self.control_loop)  # 50 Hz (20 ms)

        self.get_logger().info('L298N driver ready (PWM 1 kHz, PID 50 Hz)')

    def _detect_gpiochip(self):
        """Find the chip that owns the 40-pin header.

        Pi 5 -> pinctrl-rp1, Pi 4 and earlier -> pinctrl-bcm2835/2711.
        Falls back to 0, which is correct on a Pi 4 and on Pi 5 kernels
        from 6.6.45 onwards.
        """
        import glob
        import os
        for path in sorted(glob.glob('/sys/bus/gpio/devices/gpiochip*')):
            try:
                with open(os.path.join(path, 'label')) as fh:
                    label = fh.read().strip()
            except OSError:
                continue
            if label.startswith('pinctrl-'):
                num = int(os.path.basename(path).replace('gpiochip', ''))
                self.get_logger().info(
                    f'Autodetected header gpiochip{num} (label "{label}")')
                return num
        self.get_logger().warn(
            'Could not autodetect the header gpiochip; falling back to 0. '
            'Override with -p gpiochip:=N if the motors do not respond.')
        return 0

    # lgpio callback signature: (chip, gpio, level, timestamp)
    def _left_tick(self, _chip, _gpio, _level, _tstamp):
        self.left_ticks += self.left_dir

    def _right_tick(self, _chip, _gpio, _level, _tstamp):
        self.right_ticks += self.right_dir

    def cmd_callback(self, msg):
        half_l = self.get_parameter('wheel_separation').value / 2.0
        self.target_left = msg.linear.x - msg.angular.z * half_l
        self.target_right = msg.linear.x + msg.angular.z * half_l
        self.last_cmd_time = self.get_clock().now()

    def control_loop(self):
        dt = 0.02
        now = self.get_clock().now()
        if (now - self.last_cmd_time).nanoseconds * 1e-9 > \
                self.get_parameter('cmd_timeout').value:
            self.target_left = self.target_right = 0.0

        ticks_per_rev = self.get_parameter('encoder_ticks_per_rev').value
        radius = self.get_parameter('wheel_radius').value
        m_per_tick = 2.0 * math.pi * radius / ticks_per_rev

        d_left = (self.left_ticks - self.prev_left_ticks) * m_per_tick
        d_right = (self.right_ticks - self.prev_right_ticks) * m_per_tick
        self.prev_left_ticks = self.left_ticks
        self.prev_right_ticks = self.right_ticks
        v_left = d_left / dt
        v_right = d_right / dt

        max_speed = self.get_parameter('max_wheel_speed').value
        ff_left = 100.0 * self.target_left / max_speed
        ff_right = 100.0 * self.target_right / max_speed
        duty_left = ff_left + self.pid_left.step(self.target_left - v_left, dt)
        duty_right = ff_right + self.pid_right.step(self.target_right - v_right, dt)
        self._set_motor('a', duty_left)
        self._set_motor('b', duty_right)
        self.left_dir = 1 if duty_left >= 0 else -1
        self.right_dir = 1 if duty_right >= 0 else -1

        # Odometry integration (differential drive kinematics, Section 3.3)
        d_center = (d_left + d_right) / 2.0
        d_theta = (d_right - d_left) / self.get_parameter('wheel_separation').value
        self.x += d_center * math.cos(self.theta + d_theta / 2.0)
        self.y += d_center * math.sin(self.theta + d_theta / 2.0)
        self.theta = math.atan2(math.sin(self.theta + d_theta),
                                math.cos(self.theta + d_theta))
        self.publish_odometry(now, d_center / dt, d_theta / dt)

    def _set_motor(self, channel, duty):
        duty = max(-100.0, min(100.0, duty))
        lgpio = self.lgpio
        if channel == 'a':
            lgpio.gpio_write(self.handle, self.pins['in1_pin'], int(duty >= 0))
            lgpio.gpio_write(self.handle, self.pins['in2_pin'], int(duty < 0))
            lgpio.tx_pwm(self.handle, self.pins['ena_pin'],
                         self.pwm_freq, abs(duty))
        else:
            lgpio.gpio_write(self.handle, self.pins['in3_pin'], int(duty >= 0))
            lgpio.gpio_write(self.handle, self.pins['in4_pin'], int(duty < 0))
            lgpio.tx_pwm(self.handle, self.pins['enb_pin'],
                         self.pwm_freq, abs(duty))

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
            # Stop the motors BEFORE releasing the chip, or the L298N holds
            # whatever duty cycle was last latched and the robot drives on.
            self.lgpio.tx_pwm(self.handle, self.pins['ena_pin'],
                              self.pwm_freq, 0)
            self.lgpio.tx_pwm(self.handle, self.pins['enb_pin'],
                              self.pwm_freq, 0)
            self._left_cb.cancel()
            self._right_cb.cancel()
            self.lgpio.gpiochip_close(self.handle)
        except Exception:  # noqa: BLE001
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = L298nDriverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
