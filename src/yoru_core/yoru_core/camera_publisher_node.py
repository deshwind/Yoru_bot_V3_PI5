"""Robot camera publisher (USB webcam via OpenCV/V4L2).

Publishes /camera/image_raw for the incident emailer's close-up shots and
any on-robot perception.

For the Raspberry Pi Camera Module (ribbon cable) use the 'camera_ros'
package instead (libcamera based); real_robot.launch.py selects between
them with the camera:=picam|usb|none argument.

On a Pi 5 + Ubuntu 24.04, camera_ros must be built from source against
Raspberry Pi's libcamera fork - see setup_pi_camera.sh. This V4L2/OpenCV
node needs none of that, which makes camera:=usb the reliable fallback if
the libcamera build gives trouble.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image

import cv2
import numpy as np
from cv_bridge import CvBridge


class CameraPublisherNode(Node):

    def __init__(self):
        super().__init__('camera_publisher_node')

        self.declare_parameter('device', 0)
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 5.0)
        self.declare_parameter('frame_id', 'camera_link_optical')
        self.declare_parameter('topic', '/camera/image_raw')
        # JPEG quality for the companion /compressed topic (see below)
        self.declare_parameter('jpeg_quality', 70)

        self.bridge = CvBridge()
        device = int(self.get_parameter('device').value)
        self.capture = cv2.VideoCapture(device)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH,
                         int(self.get_parameter('width').value))
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT,
                         int(self.get_parameter('height').value))
        if not self.capture.isOpened():
            self.get_logger().error(
                f'Cannot open camera /dev/video{device}. '
                'Node stays alive and retries every 5 s.')

        topic = self.get_parameter('topic').value
        self.pub = self.create_publisher(Image, topic, 2)

        # Companion JPEG topic. camera_ros (the picam path) gets this for
        # free from image_transport, and both yoru_real.yaml's
        # robot_camera_topic and the incident emailer default to
        # '/camera/image_raw/compressed'. Publishing raw only would leave
        # the dashboard's robot pane blank and the evidence email without
        # its close-up whenever camera:=usb is used - which is exactly the
        # fallback recommended when the Pi 5 libcamera build misbehaves.
        # It also matters over Wi-Fi: raw 640x480 is ~1 MB a frame, JPEG
        # ~45 KB, and that was the difference between an unusable and a
        # usable feed on campus Wi-Fi.
        self.compressed_pub = self.create_publisher(
            CompressedImage, topic + '/compressed', 2)

        fps = max(self.get_parameter('fps').value, 0.5)
        self.create_timer(1.0 / fps, self.tick)
        self.create_timer(5.0, self.reopen_if_needed)
        self.get_logger().info(
            f'Camera publisher: /dev/video{device} -> '
            f'{self.get_parameter("topic").value} at {fps:.0f} fps')

    def reopen_if_needed(self):
        if not self.capture.isOpened():
            self.capture.open(int(self.get_parameter('device').value))

    def tick(self):
        if not self.capture.isOpened():
            return
        ok, frame = self.capture.read()
        if not ok:
            return
        stamp = self.get_clock().now().to_msg()
        frame_id = self.get_parameter('frame_id').value

        msg = self.bridge.cv2_to_imgmsg(frame, 'bgr8')
        msg.header.stamp = stamp
        msg.header.frame_id = frame_id
        self.pub.publish(msg)

        quality = int(self.get_parameter('jpeg_quality').value)
        ok, buf = cv2.imencode('.jpg', frame,
                               [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if ok:
            jpeg = CompressedImage()
            jpeg.header.stamp = stamp
            jpeg.header.frame_id = frame_id
            jpeg.format = 'jpeg'
            jpeg.data = np.asarray(buf).tobytes()
            self.compressed_pub.publish(jpeg)

    def destroy_node(self):
        try:
            self.capture.release()
        except Exception:  # noqa: BLE001
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraPublisherNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
