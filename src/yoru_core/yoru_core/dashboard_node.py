"""Admin web dashboard node (Yoru V3).

Serves the password-protected admin console using only the Python standard
library (plus cv2/cv_bridge already used elsewhere). Runs on the server
laptop; open  http://localhost:8080  (the LAN URL is printed at startup).

V2 additions over the V1 console:
  - FIRST-RUN SETUP: no password in any config file. On first launch the
    dashboard asks the admin to create a password; it is stored as a salted
    PBKDF2 hash in <data_dir>/admin.json.
  - SETUP SCREEN: keyboard (WASD / arrows) teleop for mapping, a Save Map
    button (nav2 map_saver_cli), and click-to-mark CCTV camera spots on the
    map - the spot each camera's escalation should send the robot to.
    Spots are stored in <maps_dir>/cameras.json (read live by
    camera_target_node).
  - CAMERAS SCREEN: live YOLO debug view of each CCTV pipeline and the
    robot's onboard camera.

Auth: admin password -> session token held in server memory.
"""

import glob
import hashlib
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import math

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                       qos_profile_sensor_data)
from sensor_msgs.msg import CompressedImage, Image, Joy
from std_msgs.msg import Bool, Float32, String
from tf2_ros import Buffer, TransformListener

from yoru_core.dashboard_page import PAGE_HTML

PBKDF2_ITERATIONS = 200_000


class DashboardNode(Node):

    def __init__(self):
        super().__init__('dashboard_node')

        self.declare_parameter('port', 8080)
        self.declare_parameter('log_dir', os.path.expanduser('~/compliance_robot_logs'))
        self.declare_parameter('data_dir', os.path.expanduser('~/Yoru_bot_V3/data'))
        self.declare_parameter('maps_dir', os.path.expanduser('~/Yoru_bot_V3/maps'))
        self.declare_parameter('map_name', 'main_map')
        self.declare_parameter('drive_speed', 0.2)
        self.declare_parameter('turn_speed', 0.8)
        self.declare_parameter('cctv_image_topics', ['/compliance/cctv1/debug_image'])
        self.declare_parameter('robot_camera_topic', '/camera/image_raw')

        self.data_dir = os.path.expanduser(self.get_parameter('data_dir').value)
        self.maps_dir = os.path.expanduser(self.get_parameter('maps_dir').value)
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.maps_dir, exist_ok=True)
        self.admin_file = os.path.join(self.data_dir, 'admin.json')
        self.cameras_file = os.path.join(self.maps_dir, 'cameras.json')
        self.bases_file = os.path.join(self.maps_dir, 'bases.json')

        self.lock = threading.Lock()
        self.tokens = set()
        self.state = {
            'fsm': {}, 'paused': False, 'nav': '', 'base': '',
            'battery': None, 'joy_seen': 0.0, 'alert': None,
        }
        self.drive_cmd = (0.0, 0.0)
        self.drive_time = 0.0
        self.estop_until = 0.0
        self.bridge = CvBridge()
        self.frames = {}          # 'cctv0', 'cctv1', 'robot' -> latest BGR frame
        self.frame_times = {}
        self.frame_seq = {}       # per-key counter, drives the MJPEG streams
        self.frame_cond = threading.Condition()
        self.map_msg_count = 0
        self.map_msg_time = 0.0

        self.pause_pub = self.create_publisher(Bool, '/compliance/autonomy_paused', 10)
        self.home_pub = self.create_publisher(Bool, '/compliance/return_to_base', 10)
        # Test-announcement button: exercises the real PA path end-to-end
        self.pa_pub = self.create_publisher(String, '/compliance/pa_warning', 10)
        self.map_reset_pub = self.create_publisher(String, '/compliance/map_reset', 10)
        # cmd_vel_tracker: twist_mux priority 20 (above Nav2, below joystick)
        self.drive_pub = self.create_publisher(Twist, 'cmd_vel_tracker', 10)
        # Relocalisation: consumed by AMCL / slam_toolbox localization mode
        self.initialpose_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/initialpose', 10)

        # Live map (slam_toolbox publishes /map latched / transient local)
        self.map_png = b''
        self.map_meta = {}
        map_qos = QoSProfile(depth=1,
                             reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, '/map', self.map_callback, map_qos)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.latest_target_xy = None
        self.create_subscription(PoseStamped, '/compliance/navigation_targets',
                                 self.target_callback, 10)

        self.costmap_clients = {}
        try:
            from nav2_msgs.srv import ClearEntireCostmap
            for name in ('/global_costmap/clear_entirely_global_costmap',
                         '/local_costmap/clear_entirely_local_costmap'):
                self.costmap_clients[name] = self.create_client(
                    ClearEntireCostmap, name)
        except ImportError:
            pass

        self.create_subscription(String, '/compliance/fsm_status',
                                 self.fsm_callback, 10)
        self.create_subscription(Bool, '/compliance/autonomy_paused',
                                 self.paused_callback, 10)
        self.create_subscription(String, '/compliance/nav_status',
                                 lambda m: self.json_state('nav', m), 10)
        self.create_subscription(String, '/compliance/return_to_base_status',
                                 lambda m: self.json_state('base', m), 10)
        self.create_subscription(Float32, '/compliance/battery_level',
                                 self.battery_callback, 10)
        self.create_subscription(Joy, '/joy', self.joy_callback, 10)
        self.create_subscription(String, '/compliance/event_metadata',
                                 self.metadata_callback, 10)

        # Live camera views (CCTV debug images + robot onboard camera).
        # '/compressed' topics carry JPEG (small + smooth at high fps).
        for i, topic in enumerate(self.get_parameter('cctv_image_topics').value):
            if topic.endswith('/compressed'):
                self.create_subscription(
                    CompressedImage, topic,
                    lambda m, key=f'cctv{i}': self.compressed_image_callback(key, m),
                    qos_profile_sensor_data)
            else:
                self.create_subscription(
                    Image, topic,
                    lambda m, key=f'cctv{i}': self.image_callback(key, m),
                    qos_profile_sensor_data)
        # The robot camera crosses Wi-Fi: use the .../compressed topic there
        # (raw 640x480 frames are ~1MB each and don't survive campus Wi-Fi).
        robot_cam = self.get_parameter('robot_camera_topic').value
        if robot_cam and robot_cam.endswith('/compressed'):
            self.create_subscription(
                CompressedImage, robot_cam,
                lambda m: self.compressed_image_callback('robot', m),
                qos_profile_sensor_data)
        elif robot_cam:
            self.create_subscription(
                Image, robot_cam,
                lambda m: self.image_callback('robot', m),
                qos_profile_sensor_data)

        self.create_timer(0.1, self.drive_tick)  # 10 Hz drive/e-stop keepalive

        port = int(self.get_parameter('port').value)
        self.server = ThreadingHTTPServer(('0.0.0.0', port), self.make_handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        setup_note = ('first run: you will be asked to CREATE the admin password'
                      if not os.path.isfile(self.admin_file) else
                      'sign in with your admin password')
        self.get_logger().info(
            f'Admin dashboard at http://localhost:{port}  |  '
            f'from your phone: http://{self.lan_ip()}:{port} '
            f'(same Wi-Fi; {setup_note})')

    @staticmethod
    def lan_ip():
        """Best-effort LAN IP (no packets are actually sent)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('10.255.255.255', 1))
                return s.getsockname()[0]
        except OSError:
            return '<server-ip>'

    # -------------------------------------------------------------- password

    def password_is_set(self):
        return os.path.isfile(self.admin_file)

    @staticmethod
    def hash_password(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode(), salt,
                                   PBKDF2_ITERATIONS).hex()

    def store_password(self, password):
        salt = secrets.token_bytes(16)
        record = {'salt': salt.hex(),
                  'hash': self.hash_password(password, salt),
                  'iterations': PBKDF2_ITERATIONS}
        tmp = self.admin_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(record, f)
        os.replace(tmp, self.admin_file)

    def check_password(self, password):
        try:
            with open(self.admin_file, encoding='utf-8') as f:
                record = json.load(f)
            salt = bytes.fromhex(record['salt'])
            expected = record['hash']
        except (OSError, ValueError, KeyError):
            return False
        return secrets.compare_digest(
            self.hash_password(password or '', salt), expected)

    # ----------------------------------------------------------- ROS callbacks

    def fsm_callback(self, msg):
        try:
            with self.lock:
                self.state['fsm'] = json.loads(msg.data)
        except ValueError:
            pass

    def paused_callback(self, msg):
        with self.lock:
            self.state['paused'] = msg.data

    def json_state(self, key, msg):
        try:
            with self.lock:
                self.state[key] = json.loads(msg.data).get('state', '')
        except ValueError:
            pass

    def battery_callback(self, msg):
        with self.lock:
            self.state['battery'] = round(msg.data, 1)

    def joy_callback(self, _msg):
        with self.lock:
            self.state['joy_seen'] = time.monotonic()

    def metadata_callback(self, msg):
        """Latest detection verdict, shown live on the Cameras screen."""
        try:
            meta = json.loads(msg.data)
        except ValueError:
            return
        with self.lock:
            self.state['alert'] = {
                'status': meta.get('status'),
                'room': meta.get('room'),
                'event_class': meta.get('event_class'),
                'confidence': meta.get('confidence'),
                'seen': time.monotonic(),
            }

    def image_callback(self, key, msg):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        except Exception:  # noqa: BLE001 - unsupported encoding
            return
        self._store_frame(key, frame)

    def compressed_image_callback(self, key, msg):
        frame = cv2.imdecode(np.frombuffer(msg.data, np.uint8),
                             cv2.IMREAD_COLOR)
        if frame is None:
            return
        self._store_frame(key, frame)

    def _store_frame(self, key, frame):
        with self.lock:
            self.frames[key] = frame
            self.frame_times[key] = time.monotonic()
            self.frame_seq[key] = self.frame_seq.get(key, 0) + 1
        with self.frame_cond:
            self.frame_cond.notify_all()   # wake the MJPEG streams

    def target_callback(self, msg):
        self.latest_target_xy = (round(msg.pose.position.x, 2),
                                 round(msg.pose.position.y, 2))

    def map_callback(self, msg):
        """Renders the occupancy grid to a PNG (walls/edges=white,
        ground=grey, unknown=transparent) and caches the world metadata
        for the client."""
        w, h = msg.info.width, msg.info.height
        grid = np.array(msg.data, dtype=np.int8).reshape(h, w)
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        free = (grid >= 0) & (grid < 50)
        occ = grid >= 50
        rgba[free] = (145, 148, 155, 255)   # ground: grey
        rgba[occ] = (255, 255, 255, 255)    # walls/edges: white
        rgba = cv2.flip(rgba, 0)  # grid origin is bottom-left; images top-left
        ok, png = cv2.imencode('.png', cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
        if not ok:
            return
        with self.lock:
            self.map_png = png.tobytes()
            self.map_msg_count += 1
            self.map_msg_time = time.monotonic()
            self.map_meta = {
                'width': w, 'height': h,
                'resolution': msg.info.resolution,
                'origin_x': msg.info.origin.position.x,
                'origin_y': msg.info.origin.position.y,
                'stamp': msg.header.stamp.sec,
            }

    def robot_pose(self):
        try:
            tf = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            q = tf.transform.rotation
            yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                             1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            return {'x': round(tf.transform.translation.x, 3),
                    'y': round(tf.transform.translation.y, 3),
                    'yaw': round(yaw, 3)}
        except Exception:  # noqa: BLE001 - TF not available yet
            return None

    def drive_tick(self):
        """Republishes the web drive command with a 0.5 s deadman timeout."""
        now = time.monotonic()
        if now < self.estop_until:
            self.drive_pub.publish(Twist())  # zeros override Nav2
            return
        lx, az = self.drive_cmd
        if (lx or az) and now - self.drive_time < 0.5:
            t = Twist()
            t.linear.x = lx
            t.angular.z = az
            self.drive_pub.publish(t)
        elif (lx or az):
            self.drive_cmd = (0.0, 0.0)
            self.drive_pub.publish(Twist())

    # ------------------------------------------------------------- properties

    def mapping_active(self):
        """slam_toolbox republishes /map continuously; a static map_server
        sends it once. More than two updates recently => SLAM/mapping mode."""
        with self.lock:
            count, last = self.map_msg_count, self.map_msg_time
        return count > 2 and time.monotonic() - last < 30.0

    def saved_map_path(self):
        name = self.get_parameter('map_name').value
        return os.path.join(self.maps_dir, name + '.yaml')

    def load_cameras(self):
        try:
            with open(self.cameras_file, encoding='utf-8') as f:
                cams = json.load(f)
            return cams if isinstance(cams, list) else []
        except (OSError, ValueError):
            return []

    def load_bases(self):
        try:
            with open(self.bases_file, encoding='utf-8') as f:
                bases = json.load(f)
            return bases if isinstance(bases, list) else []
        except (OSError, ValueError):
            return []

    # -------------------------------------------------------------- API logic

    def api_boot(self):
        """Pre-login state for the page: which screen to show first."""
        return {
            'needs_setup': not self.password_is_set(),
            'has_saved_map': os.path.isfile(self.saved_map_path()),
            'mapping_active': self.mapping_active(),
        }

    def api_setup(self, body):
        if self.password_is_set():
            return {'error': 'already configured'}, HTTPStatus.FORBIDDEN
        password = str(body.get('password', ''))
        if len(password) < 4:
            return {'error': 'password too short (min 4)'}, HTTPStatus.BAD_REQUEST
        self.store_password(password)
        token = secrets.token_hex(16)
        self.tokens.add(token)
        self.get_logger().warn('DASHBOARD: admin password created (first-run setup)')
        return {'token': token}, HTTPStatus.OK

    def api_change_password(self, body):
        if not self.check_password(str(body.get('old', ''))):
            return {'error': 'wrong current password'}, HTTPStatus.UNAUTHORIZED
        new = str(body.get('new', ''))
        if len(new) < 4:
            return {'error': 'password too short (min 4)'}, HTTPStatus.BAD_REQUEST
        self.store_password(new)
        self.get_logger().warn('DASHBOARD: admin password changed')
        return {'ok': True}, HTTPStatus.OK

    def api_status(self):
        with self.lock:
            s = dict(self.state)
        alert = s.get('alert')
        if alert and time.monotonic() - alert.get('seen', 0) > 5.0:
            alert = None  # stale detection - do not keep showing it
        return {
            'mode': 'MANUAL' if s['paused'] else 'AUTONOMOUS',
            'fsm_state': s['fsm'].get('state', 'unknown'),
            'room': s['fsm'].get('room', '') or '-',
            'stage': s['fsm'].get('stage_reached', '-'),
            'nav': s['nav'] or '-',
            'return_to_base': s['base'] or '-',
            'battery': s['battery'],
            'joystick': time.monotonic() - s['joy_seen'] < 2.0,
            'alert': ({k: alert[k] for k in
                       ('status', 'room', 'event_class', 'confidence')}
                      if alert else None),
            'mapping_active': self.mapping_active(),
            'has_saved_map': os.path.isfile(self.saved_map_path()),
        }

    def api_incidents(self):
        path = os.path.join(self.get_parameter('log_dir').value, 'incidents.jsonl')
        incidents = []
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    try:
                        incidents.append(json.loads(line))
                    except ValueError:
                        continue
        incidents = incidents[-500:][::-1]  # newest first

        per_room = {}
        complied = 0
        last24h = 0
        now = time.time()
        for inc in incidents:
            room = inc.get('room') or inc.get('room_id') or 'unknown'
            per_room[room] = per_room.get(room, 0) + 1
            if inc.get('outcome') == 'complied':
                complied += 1
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(inc['timestamp']).timestamp()
                if now - ts < 86400:
                    last24h += 1
            except (KeyError, ValueError):
                pass
        total = len(incidents)
        return {
            'stats': {
                'total': total,
                'complied': complied,
                'compliance_rate': round(100.0 * complied / total, 1) if total else 0.0,
                'last24h': last24h,
                'per_room': per_room,
            },
            'incidents': incidents,
        }

    def api_set_mode(self, body):
        paused = bool(body.get('paused'))
        self.pause_pub.publish(Bool(data=paused))
        self.get_logger().warn(
            f'DASHBOARD: autonomy {"PAUSED (admin manual)" if paused else "RESUMED"}')
        return {'ok': True}

    def api_home(self):
        self.home_pub.publish(Bool(data=True))
        self.get_logger().warn('DASHBOARD: return-to-base requested')
        return {'ok': True}

    def api_test_pa(self):
        """Publishes a test message on the real PA topic, so the same audio
        node/speaker chain used for violations proves itself in one click."""
        msg = String()
        msg.data = json.dumps({
            'message': 'This is a test announcement from the Yoru dashboard. '
                       'The public address system is working.',
            'test': True,
        })
        self.pa_pub.publish(msg)
        listeners = self.pa_pub.get_subscription_count()
        self.get_logger().warn(
            f'DASHBOARD: test announcement published ({listeners} audio '
            'node(s) listening)')
        note = '' if listeners else \
            'No audio node is subscribed - is the server fully started?'
        return {'ok': True, 'listeners': listeners, 'note': note}

    def api_stop(self):
        self.pause_pub.publish(Bool(data=True))
        self.home_pub.publish(Bool(data=False))  # also cancels a base trip
        self.estop_until = time.monotonic() + 2.0
        self.get_logger().warn('DASHBOARD: EMERGENCY STOP')
        return {'ok': True}

    def api_drive(self, body):
        scale_l = self.get_parameter('drive_speed').value
        scale_a = self.get_parameter('turn_speed').value
        lx = max(-1.0, min(1.0, float(body.get('lx', 0.0)))) * scale_l
        az = max(-1.0, min(1.0, float(body.get('az', 0.0)))) * scale_a
        self.drive_cmd = (lx, az)
        self.drive_time = time.monotonic()
        return {'ok': True}

    def api_map_info(self):
        with self.lock:
            meta = dict(self.map_meta)
        meta['robot'] = self.robot_pose()
        meta['target'] = self.latest_target_xy
        meta['has_map'] = bool(self.map_png)
        meta['mapping_active'] = self.mapping_active()
        meta['cameras'] = self.load_cameras()
        meta['bases'] = self.load_bases()
        return meta

    def api_save_map(self):
        """Saves the live SLAM map with nav2 map_saver_cli (runs on this
        machine; /map arrives over the network from the robot in mapping
        mode). The robot then localizes on it after deploy + relaunch."""
        name = self.get_parameter('map_name').value
        stem = os.path.join(self.maps_dir, name)
        cmd = ['ros2', 'run', 'nav2_map_server', 'map_saver_cli',
               '-f', stem, '--ros-args', '-p', 'save_map_timeout:=10.0']
        self.get_logger().warn(f'DASHBOARD: saving map to {stem}')
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=45)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {'error': f'map_saver failed: {exc}'}
        if proc.returncode != 0 or not os.path.isfile(stem + '.yaml'):
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
            return {'error': 'map_saver failed: ' + ' | '.join(tail)}
        return {'ok': True, 'path': stem + '.yaml'}

    def api_reset_map(self):
        """Deletes the saved map here AND on the robot, then the robot
        relaunches itself into mapping mode (map_reset_node + the
        start_robot.sh relaunch loop). Camera and base spots are cleared
        too - a new area means new spots (old coordinates would be
        meaningless on the new map)."""
        name = self.get_parameter('map_name').value
        removed = []
        for path in glob.glob(os.path.join(self.maps_dir, name + '.*')) + \
                glob.glob(os.path.join(self.maps_dir, name + '_serial.*')):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError as exc:
                return {'error': f'could not remove {path}: {exc}'}
        for spots_file in (self.cameras_file, self.bases_file):
            tmp = spots_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump([], f)
            os.replace(tmp, spots_file)
        reset = String()
        reset.data = 'reset'
        self.map_reset_pub.publish(reset)
        self.get_logger().warn(
            f'DASHBOARD: map reset (removed {removed if removed else "no local files"}); '
            'robot restarting into mapping mode')
        return {'ok': True, 'removed': removed}

    def api_cameras_get(self):
        return {'cameras': self.load_cameras()}

    def api_cameras_set(self, body):
        cams = body.get('cameras')
        if not isinstance(cams, list):
            return {'error': 'cameras must be a list'}
        clean = []
        for cam in cams:
            try:
                clean.append({
                    'id': str(cam['id']),
                    'name': str(cam.get('name', cam['id'])),
                    'x': round(float(cam['x']), 3),
                    'y': round(float(cam['y']), 3),
                    'yaw': round(float(cam.get('yaw', 0.0)), 3),
                })
            except (KeyError, TypeError, ValueError):
                return {'error': f'bad camera entry: {cam}'}
        tmp = self.cameras_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, self.cameras_file)
        self.get_logger().warn(
            f'DASHBOARD: saved {len(clean)} camera spot(s) to {self.cameras_file}')
        return {'ok': True, 'cameras': clean}

    def api_bases_get(self):
        return {'bases': self.load_bases()}

    def api_bases_set(self, body):
        bases = body.get('bases')
        if not isinstance(bases, list):
            return {'error': 'bases must be a list'}
        clean = []
        for base in bases:
            try:
                clean.append({
                    'id': str(base['id']),
                    'name': str(base.get('name', base['id'])),
                    'x': round(float(base['x']), 3),
                    'y': round(float(base['y']), 3),
                    'yaw': round(float(base.get('yaw', 0.0)), 3),
                })
            except (KeyError, TypeError, ValueError):
                return {'error': f'bad base entry: {base}'}
        tmp = self.bases_file + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(clean, f, indent=2)
        os.replace(tmp, self.bases_file)
        self.get_logger().warn(
            f'DASHBOARD: saved {len(clean)} base spot(s) to {self.bases_file}')
        return {'ok': True, 'bases': clean}

    def api_relocalise(self, body):
        pose = PoseWithCovarianceStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.pose.position.x = float(body.get('x', 0.0))
        pose.pose.pose.position.y = float(body.get('y', 0.0))
        yaw = float(body.get('yaw', 0.0))
        pose.pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.pose.orientation.w = math.cos(yaw / 2.0)
        pose.pose.covariance[0] = 0.25   # x
        pose.pose.covariance[7] = 0.25   # y
        pose.pose.covariance[35] = 0.068  # yaw
        self.initialpose_pub.publish(pose)
        listeners = self.initialpose_pub.get_subscription_count()
        self.get_logger().warn(
            f'DASHBOARD: relocalise to ({pose.pose.pose.position.x:.2f}, '
            f'{pose.pose.pose.position.y:.2f}, yaw {yaw:.2f}) - '
            f'{listeners} localisation node(s) listening')
        note = '' if listeners else \
            'No localisation node is listening (SLAM mapping mode localises itself).'
        return {'ok': True, 'listeners': listeners, 'note': note}

    def api_clear_costmaps(self):
        cleared = 0
        for name, client in self.costmap_clients.items():
            if client.service_is_ready():
                client.call_async(client.srv_type.Request())
                cleared += 1
        self.get_logger().warn(f'DASHBOARD: clear costmaps ({cleared} services)')
        return {'ok': True, 'cleared': cleared}

    def get_camera_jpeg(self, key):
        with self.lock:
            frame = self.frames.get(key)
            seen = self.frame_times.get(key, 0.0)
        if frame is None or time.monotonic() - seen > 10.0:
            return None
        ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return jpg.tobytes() if ok else None

    def stream_camera(self, wfile, key):
        """Pushes an MJPEG stream (multipart/x-mixed-replace): every new
        frame is written the moment it arrives - smooth CCTV-style video
        instead of the old snapshot polling. Runs in the request thread
        until the browser disconnects."""
        last_seq = -1
        while True:
            with self.frame_cond:
                self.frame_cond.wait(timeout=2.0)
            with self.lock:
                seq = self.frame_seq.get(key, 0)
                frame = self.frames.get(key)
            if frame is None or seq == last_seq:
                continue   # no new frame for THIS camera yet
            last_seq = seq
            ok, jpg = cv2.imencode('.jpg', frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            try:
                wfile.write(b'--yoruframe\r\n'
                            b'Content-Type: image/jpeg\r\n'
                            b'Content-Length: ' + str(len(jpg)).encode()
                            + b'\r\n\r\n' + jpg.tobytes() + b'\r\n')
            except (BrokenPipeError, ConnectionResetError, OSError):
                return   # viewer closed the page/tab

    # ------------------------------------------------------------ HTTP server

    def make_handler(self):
        node = self

        class Handler(BaseHTTPRequestHandler):

            def log_message(self, *args):  # silence per-request stderr spam
                pass

            def send_json(self, payload, code=HTTPStatus.OK):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def send_bytes(self, data, ctype):
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)

            def authed(self):
                token = self.headers.get('X-Auth', '')
                return token in node.tokens

            def read_body(self):
                length = int(self.headers.get('Content-Length', 0))
                try:
                    return json.loads(self.rfile.read(length) or b'{}')
                except ValueError:
                    return {}

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == '/' or url.path.startswith('/index'):
                    data = PAGE_HTML.encode()
                    self.send_bytes(data, 'text/html; charset=utf-8')
                    return
                if url.path == '/api/boot':
                    self.send_json(node.api_boot())
                    return
                if url.path == '/api/stream.mjpg':
                    # <img> tags cannot send headers: token comes as ?t=
                    qs = parse_qs(url.query)
                    token = qs.get('t', [''])[0] or self.headers.get('X-Auth', '')
                    if token not in node.tokens:
                        self.send_json({'error': 'unauthorized'},
                                       HTTPStatus.UNAUTHORIZED)
                        return
                    key = qs.get('src', ['cctv0'])[0]
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type',
                                     'multipart/x-mixed-replace; '
                                     'boundary=yoruframe')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    node.stream_camera(self.wfile, key)
                    return
                if not self.authed():
                    self.send_json({'error': 'unauthorized'}, HTTPStatus.UNAUTHORIZED)
                    return
                if url.path == '/api/status':
                    self.send_json(node.api_status())
                elif url.path == '/api/incidents':
                    self.send_json(node.api_incidents())
                elif url.path == '/api/map_info':
                    self.send_json(node.api_map_info())
                elif url.path == '/api/cameras':
                    self.send_json(node.api_cameras_get())
                elif url.path == '/api/bases':
                    self.send_json(node.api_bases_get())
                elif url.path == '/api/cam.jpg':
                    key = parse_qs(url.query).get('src', ['cctv0'])[0]
                    jpg = node.get_camera_jpeg(key)
                    if jpg is None:
                        self.send_json({'error': 'no frame'}, HTTPStatus.NOT_FOUND)
                    else:
                        self.send_bytes(jpg, 'image/jpeg')
                elif url.path == '/api/map.png':
                    with node.lock:
                        png = node.map_png
                    if not png:
                        self.send_json({'error': 'no map yet'},
                                       HTTPStatus.NOT_FOUND)
                    else:
                        self.send_bytes(png, 'image/png')
                else:
                    self.send_json({'error': 'not found'}, HTTPStatus.NOT_FOUND)

            def do_POST(self):
                body = self.read_body()
                if self.path == '/api/setup':
                    payload, code = node.api_setup(body)
                    self.send_json(payload, code)
                    return
                if self.path == '/api/login':
                    if not node.password_is_set():
                        self.send_json({'error': 'setup required'},
                                       HTTPStatus.CONFLICT)
                    elif node.check_password(str(body.get('password', ''))):
                        token = secrets.token_hex(16)
                        node.tokens.add(token)
                        self.send_json({'token': token})
                    else:
                        node.get_logger().warn('Dashboard: failed login attempt')
                        self.send_json({'error': 'wrong password'},
                                       HTTPStatus.UNAUTHORIZED)
                    return
                if not self.authed():
                    self.send_json({'error': 'unauthorized'}, HTTPStatus.UNAUTHORIZED)
                    return
                if self.path == '/api/mode':
                    self.send_json(node.api_set_mode(body))
                elif self.path == '/api/home':
                    self.send_json(node.api_home())
                elif self.path == '/api/test_pa':
                    self.send_json(node.api_test_pa())
                elif self.path == '/api/stop':
                    self.send_json(node.api_stop())
                elif self.path == '/api/drive':
                    self.send_json(node.api_drive(body))
                elif self.path == '/api/relocalise':
                    self.send_json(node.api_relocalise(body))
                elif self.path == '/api/clear_costmaps':
                    self.send_json(node.api_clear_costmaps())
                elif self.path == '/api/save_map':
                    self.send_json(node.api_save_map())
                elif self.path == '/api/reset_map':
                    self.send_json(node.api_reset_map())
                elif self.path == '/api/cameras':
                    self.send_json(node.api_cameras_set(body))
                elif self.path == '/api/bases':
                    self.send_json(node.api_bases_set(body))
                elif self.path == '/api/change_password':
                    payload, code = node.api_change_password(body)
                    self.send_json(payload, code)
                else:
                    self.send_json({'error': 'not found'}, HTTPStatus.NOT_FOUND)

        return Handler

    def destroy_node(self):
        self.server.shutdown()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DashboardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
