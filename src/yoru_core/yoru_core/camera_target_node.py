"""Camera target node (Yoru V2).

Replaces V1's pixel-to-map coordinate transform with the camera-spot
registry: the admin marks, on the saved map in the dashboard, the exact
spot the robot should drive to for each CCTV camera. When this camera's
pipeline confirms a smoking event, the marked pose is published as the
navigation target - no per-camera calibration needed, and moving the
camera slightly never breaks navigation.

The registry (maps/cameras.json, written by the dashboard) is a list:
    [{"id": "cctv1", "name": "Camera 1", "x": 1.2, "y": 3.4, "yaw": 0.0}]
The file is re-read whenever its modification time changes, so spots
marked in the dashboard apply immediately without restarting.
"""

import json
import math
import os

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from vision_msgs.msg import Detection2DArray
from visualization_msgs.msg import Marker


class CameraTargetNode(Node):

    def __init__(self):
        super().__init__('camera_target_node')

        self.declare_parameter('camera_id', 'cctv1')
        self.declare_parameter('cameras_file',
                               os.path.expanduser('~/Yoru_bot_V3/maps/cameras.json'))
        self.declare_parameter('input_topic', '/compliance/cctv1/confirmed')

        self.cameras = {}
        self.file_mtime = 0.0

        self.target_pub = self.create_publisher(
            PoseStamped, '/compliance/navigation_targets', 10)
        self.marker_pub = self.create_publisher(
            Marker, '/compliance/target_marker', 5)
        self.create_subscription(
            Detection2DArray, self.get_parameter('input_topic').value,
            self.events_callback, 10)

        self.reload_cameras()
        self.get_logger().info(
            f'Camera target node ready (camera_id='
            f'{self.get_parameter("camera_id").value}, '
            f'registry={self.get_parameter("cameras_file").value})')

    def reload_cameras(self):
        """Re-reads cameras.json when it changed on disk."""
        path = os.path.expanduser(self.get_parameter('cameras_file').value)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            self.cameras = {}
            return
        if mtime == self.file_mtime:
            return
        try:
            with open(path, encoding='utf-8') as f:
                entries = json.load(f)
            self.cameras = {c['id']: c for c in entries if 'id' in c}
            self.file_mtime = mtime
            self.get_logger().info(
                f'Loaded {len(self.cameras)} camera spot(s) from {path}')
        except (ValueError, OSError, KeyError) as exc:
            self.get_logger().warn(f'Could not read {path}: {exc}')

    def events_callback(self, msg):
        if not msg.detections:
            return
        self.reload_cameras()
        camera_id = self.get_parameter('camera_id').value
        spot = self.cameras.get(camera_id)
        if spot is None:
            self.get_logger().warn(
                f'No marked spot for "{camera_id}" in cameras.json - '
                'mark it on the map in the dashboard (Setup screen)',
                throttle_duration_sec=10.0)
            return

        yaw = float(spot.get('yaw', 0.0))
        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = 'map'
        pose.pose.position.x = float(spot['x'])
        pose.pose.position.y = float(spot['y'])
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        self.target_pub.publish(pose)
        self.publish_marker(float(spot['x']), float(spot['y']))

    def publish_marker(self, x, y):
        marker = Marker()
        marker.header.frame_id = 'map'
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = 'compliance_target'
        marker.id = 0
        marker.type = Marker.CYLINDER
        marker.action = Marker.ADD
        marker.pose.position.x = x
        marker.pose.position.y = y
        marker.pose.position.z = 0.05
        marker.pose.orientation.w = 1.0
        marker.scale.x = marker.scale.y = 0.4
        marker.scale.z = 0.1
        marker.color.r = 1.0
        marker.color.a = 0.8
        marker.lifetime.sec = 5
        self.marker_pub.publish(marker)


def main(args=None):
    rclpy.init(args=args)
    node = CameraTargetNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
