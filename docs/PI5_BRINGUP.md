# Raspberry Pi 5 bring-up checklist

Work through this **in order**. Each stage has a command, the output that
means it worked, and the failure you are most likely to hit. Do not move on
until a stage passes — almost every confusing failure later is an earlier
stage that half-worked.

The port from V2 (Humble / Pi 4) to V3 (Jazzy / Pi 5) touched the velocity
chain, the SLAM lifecycle and every Gazebo plugin. Several of the new failure
modes are **silent**: the process starts, logs look healthy, and no data
flows. That is what the "expected output" columns are for — check them
rather than trusting that a node launched.

---

## Stage 0 — Hardware and power

The Pi 5 is much less forgiving about power than the Pi 4, and this robot
loads it heavily: RPLIDAR (~300 mA), Arduino Nano Every, USB speaker, plus a
camera on the CSI bus.

- Use the **official 27 W USB-C PD supply (5.1 V / 5 A)**. A 3 A phone
  charger will boot the Pi and then brown out when the lidar motor spins up.
- On a non-PD supply the Pi 5 limits total USB current to 600 mA, which is
  not enough for lidar + Arduino + speaker together.
- Check for undervoltage after a few minutes of running:
  ```bash
  vcgencmd get_throttled
  ```
  `throttled=0x0` is good. Anything with bit 0 set (`0x50005`, `0x50000`,
  ...) means undervoltage has occurred — **fix the supply before debugging
  anything else**. Brown-outs produce exactly the symptoms that look like
  software bugs: lidar dropouts, phantom scan spikes, serial resyncs.
- The Pi 5 runs hot enough to throttle under sustained load. Use the active
  cooler; without it a long mapping run will thermal-throttle and SLAM will
  fall behind.

If running from a battery, the lidar and motors should be on their own
supply rail, not drawing through the Pi.

---

## Stage 1 — OS and ROS 2

```bash
cat /etc/os-release | head -2
ls /opt/ros/
uname -m
```

**Expected:** Ubuntu **24.04** (Noble), a `jazzy` directory, `aarch64`.

Jazzy's Tier-1 platform is Ubuntu 24.04. If you are on 22.04 there are no
`ros-jazzy-*` packages and nothing below will install.

```bash
source /opt/ros/jazzy/setup.bash
echo $ROS_DISTRO          # -> jazzy
ros2 doctor --report | head -20
```

> **Both machines must be on Jazzy.** Humble and Jazzy are not
> interoperable — different message definitions and RMW versions. A Humble
> laptop talking to a Jazzy Pi will discover each other and then exchange
> nothing, with no error on either side.

---

## Stage 2 — Provisioning

On the Pi:

```bash
cd ~/Yoru_bot_V3
./setup_pi.sh
```

**Expected:** the platform check prints `Raspberry Pi 5`, Ubuntu 24.04 and
`ROS: jazzy`, then apt installs, then the venv and udev sections, then the
camera build (Stage 6).

Skip the slow camera build for now if you want to get driving first:

```bash
./setup_pi.sh --no-camera
```

**Log out and back in** afterwards — the `dialout`/`video`/`gpio` group
changes only apply to a new session. Verify:

```bash
groups        # must list dialout and video
```

Missing `dialout` is the cause of `Permission denied: '/dev/arduino'`.

### Why there is a venv

Ubuntu 24.04 enforces PEP 668, so `pip3 install --user` now fails with
`error: externally-managed-environment`. Anything without a Debian package
(piper-tts) lives in `~/yoru_venv`, which `start_robot.sh` puts on
`PYTHONPATH` rather than activating — activating it would hide the system
`rclpy` and `cv_bridge`.

```bash
ls ~/yoru_venv/bin/piper     # should exist
```

---

## Stage 3 — Devices

```bash
ls -l /dev/rplidar /dev/arduino
```

**Expected:** two symlinks, e.g. `/dev/rplidar -> ttyUSB0` and
`/dev/arduino -> ttyACM0`.

**If missing:** replug the USB devices (udev rules only fire on connect),
then:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Still missing? Your hardware IDs differ from the rules. Find the real ones:

```bash
udevadm info -a -n /dev/ttyUSB0 | grep -E 'idVendor|idProduct' | head -4
```

and edit `udev/99-yoru.rules`. The defaults assume an RPLIDAR A1 on a
Silicon Labs CP2102 (`10c4:ea60`) and an official Arduino Nano Every
(`2341:0058`).

> **Why symlinks at all:** V2 addressed the lidar by USB by-path
> (`platform-fd500000.pcie-...`). That string encodes the **Pi 4's** PCIe
> controller address. The Pi 5 has a different SoC and an RP1 southbridge, so
> the path does not exist and the driver exits at startup.

---

## Stage 4 — Lidar

```bash
source /opt/ros/jazzy/setup.bash && source install/setup.bash
ros2 launch yoru_base rplidar.launch.py
```

**Expected:** `RPLidar health status : OK`, then scanning. In a second
terminal:

```bash
ros2 topic hz /scan          # ~10 Hz
ros2 topic echo /scan --once | head -12
```

Check in the echo output:
- `frame_id: laser_frame` — if it is anything else, TF will not resolve and
  both costmaps will silently discard every scan
- `range_min: 0.3` — deliberate. The lidar sees the robot's own frame at
  ~0.18 m; unfiltered, those self-hits speckle the whole map and trip the
  FSM emergency stop on every approach. The cost is a genuine 0.3 m blind
  ring.

**`Operation timed out` / no health status:** wrong port or wrong baud. The
A1 is 115200; the driver's own default suits the A2/A3. Override the port
if the udev symlink is absent:

```bash
ros2 launch yoru_base rplidar.launch.py serial_port:=/dev/ttyUSB0
```

---

## Stage 5 — Motors and odometry

Flash the firmware first if you have not (from the Pi):

```bash
arduino-cli compile -b arduino:megaavr:nona4809 firmware/yoru_motor_bridge
arduino-cli upload -p /dev/arduino -b arduino:megaavr:nona4809 \
    firmware/yoru_motor_bridge
```

The FQBN is `nona4809`, **not** `nanoevery`.

```bash
ros2 run yoru_core arduino_driver_node --ros-args \
    --params-file src/yoru_bringup/config/yoru_real.yaml
```

**Expected:** `Arduino motor bridge ready on /dev/arduino (1320 counts/rev)`.

**`No yoru_motor_bridge firmware answering`:** the sketch is not running, or
something else holds the port. The node sends `b` and expects the baud rate
echoed back.

Now prove the velocity chain end to end. **Put the robot on blocks** — the
wheels will turn.

```bash
# terminal 2
ros2 topic pub -r 10 /cmd_vel_mux geometry_msgs/msg/Twist \
    '{linear: {x: 0.05}, angular: {z: 0.0}}'
# terminal 3
ros2 topic echo /odom --field pose.pose.position
```

**Expected:** wheels turn forward, `x` increases steadily. Stop the publisher
and the firmware's 2 s dead-man halts the motors.

### The topic is `/cmd_vel_mux`, not `/diff_cont/cmd_vel_unstamped`

This changed in the port. Jazzy's `diff_drive_controller` takes
`TwistStamped` only — `use_stamped_vel` was removed and
`~/cmd_vel_unstamped` no longer exists. The whole twist_mux chain therefore
stays on plain `Twist` and publishes `/cmd_vel_mux`, which
`arduino_driver_node` reads directly. Only the **simulation** converts, via
`twist_stamper_node`, because gz_ros2_control is the only consumer that
needs a stamp.

### Odometry sanity

Drive a measured 1 m and compare against `/odom`. `enc_counts_per_rev`
(1320) scales every distance the robot believes it travelled, and it was
measured by hand rotation — earlier sessions disagreed badly (~1965 vs
~3166). If maps come out smeared or the robot overshoots and undershoots
goals, **verify this constant before touching Nav2**.

Carpet makes it worse: the pile deforms, the effective rolling radius
differs from the measured 43.5 mm, and slip is invisible to the encoders.

---

## Stage 6 — Camera

This is the most fragile part of the Pi 5 port. Read
`setup_pi_camera.sh`'s header comment if it misbehaves.

First, is the sensor even on the bus?

```bash
dmesg | grep -i imx477
```

**Expected:** lines naming the sensor. **If empty**, the Pi 5 on Ubuntu does
not auto-detect the way Raspberry Pi OS does. Edit
`/boot/firmware/config.txt`:

```
camera_auto_detect=0
dtoverlay=imx477            # HQ camera. imx708=v3, imx219=v2, ov5647=v1
```

The Pi 5 has **two** camera connectors — add `,cam0` or `,cam1` to pick one.
Reboot. This is a config/cable problem, not a build problem; building
camera_ros will not fix it.

Then:

```bash
./setup_pi_camera.sh          # ~15-25 min
source ~/camera_ws/install/setup.bash
ros2 run camera_ros camera_node --ros-args -p width:=640 -p height:=480
```

**Expected:** a log line naming your sensor, e.g.
`found camera /base/axi/pcie@1000120000/rp1/i2c@88000/imx477@1a`. Then:

```bash
ros2 topic hz /camera/image_raw
```

### `no cameras available` — the one you will actually hit

Do **not** install `ros-jazzy-camera-ros` from apt. It links against
Ubuntu's **upstream** libcamera, which ships no Raspberry Pi pipeline
handlers. The Pi 5 needs `rpi/pisp`; its ISP is completely different from the
Pi 4's `rpi/vc4`. The apt build reports `no cameras available` no matter how
correct your cable and config.txt are. `setup_pi_camera.sh` builds Raspberry
Pi's libcamera fork and camera_ros against it, and removes the apt package
if present.

### The escape hatch

The onboard camera only feeds evidence close-ups and the dashboard view —
**not** the YOLO pipeline, which runs on the laptop. If libcamera fights
you, use a USB webcam and move on:

```bash
./start_robot.sh camera:=usb
```

`camera_publisher_node` is plain V4L2 via OpenCV and needs none of the above.

---

## Stage 7 — TF tree

```bash
ros2 launch yoru_base rsp.launch.py use_sim_time:=false use_ros2_control:=false
ros2 run tf2_tools view_frames && ros2 run tf2_ros tf2_echo odom base_link
```

**Expected chain:** `odom -> base_link -> chassis -> {laser_frame,
camera_link}`, plus `base_footprint`.

`base_footprint` matters: it is AMCL's `base_frame_id` and slam_toolbox's
`base_frame`. If it is missing, localisation fails with transform timeouts.

---

## Stage 8 — SLAM (mapping)

```bash
./start_robot.sh mode:=mapping
```

**Expected, and check this specifically:**

```
[yoru] slam_toolbox configured, activating.
```

```bash
ros2 topic hz /map                      # ~0.2 Hz (map_update_interval 5.0)
ros2 lifecycle get /slam_toolbox        # -> active [3]
```

### The silent failure to watch for

In Jazzy, `async_slam_toolbox_node` is a **LifecycleNode**. V2 launched it as
a plain Node. On Jazzy that still starts the process — the logs look
healthy, `ros2 node list` shows `/slam_toolbox` — but it stays
`unconfigured` forever: no `/scan` subscription, no `/map`, no `map->odom`.
A robot that boots perfectly and never maps anything.

`online_async_launch.py` now drives the configure→activate transitions. If
`ros2 lifecycle get /slam_toolbox` says `unconfigured [1]`, that mechanism
is not firing — check for a `configure` failure above it in the log.

### Mapping technique

Drive **slowly** from the dashboard Setup screen (W/A/S/D). Gentle turns
give the cleanest scans; turning in place is the worst case for odometry
drift, because wheel slip is invisible to the encoders. Then **Save Map**.

---

## Stage 9 — Nav2

With a saved map present, `mode:=auto` resolves to localization:

```bash
./start_robot.sh
```

```bash
ros2 lifecycle get /bt_navigator          # -> active [3]
ros2 topic echo /amcl_pose --once
ros2 action list | grep navigate_to_pose
```

**Expected:** every lifecycle node reaches `active`. The bringup is
deliberately staged — the lifecycle manager starts 8 s late with
`bond_timeout: 60.0` — because discovery over the FastDDS discovery server
is slow enough on the Pi that the default 4 s bond timeout intermittently
aborted the whole navigation bringup.

Send a goal from RViz or the dashboard and watch:

```bash
ros2 topic echo /cmd_vel        # Nav2's output, plain Twist
ros2 topic echo /cmd_vel_mux    # after twist_mux arbitration
```

Both must carry data while navigating. **If `/cmd_vel` has data and
`/cmd_vel_mux` is silent, twist_mux is not passing anything through** — see
the box below.

### If nothing moves and there is no error

twist_mux reads `use_stamped` **without declaring it** and defaults it to
`true` when absent. That flag switches *both* its subscriptions and its
publisher between `Twist` and `TwistStamped`. Unset, twist_mux subscribes as
`TwistStamped` while Nav2, the dashboard and the FSM e-stop all publish
`Twist` — and because ROS 2 matches topics by type, nothing connects and
**nothing is logged**. The robot ignores every velocity command and the
emergency stop is silently dead.

`config/twist_mux.yaml` pins `use_stamped: false`. Do not remove it. Verify:

```bash
ros2 param get /twist_mux use_stamped     # -> false
ros2 topic info /cmd_vel_mux -v           # publisher AND subscriber, type Twist
```

### If Nav2 accepts a goal and then never moves

Check nothing is stuck on simulated time:

```bash
ros2 param get /controller_server use_sim_time      # -> false on the robot
```

`nav2_params.yaml` no longer hardcodes `use_sim_time` anywhere — the launch
argument is the single source of truth. V2 hardcoded `True` in ~15 sections,
which on the real robot means Nav2 waits forever for a `/clock` that never
comes, logging nothing useful.

---

## Stage 10 — Networking between Pi and laptop

`start_robot.sh` starts a FastDDS discovery server on the Pi, because
university and corporate Wi-Fi block the multicast that ROS 2 normally uses
to find peers.

```bash
# on the Pi
hostname -I
pgrep -af "fastdds discovery"
```

Put that IP in `ros_network.env` on **both** machines:

```bash
export ROS_DISCOVERY_SERVER=<pi-ip>:11811
```

From the laptop:

```bash
source ros_network.env
ros2 topic list | grep scan       # should see the Pi's topics
```

**Symptom of a stale IP:** each machine works alone, but the dashboard shows
no map, no robot camera, and the joystick does not drive the robot. DHCP
renewal breaks this — it is the least robust part of the system.

---

## Stage 11 — Server side

On the laptop:

```bash
./start_server.sh
```

Dashboard at <http://localhost:8080>. First run asks you to create the admin
password (stored as a salted hash in `data/admin.json`).

Check:
- **Setup** screen: keyboard drive works, map renders
- **Cameras** screen: CCTV MJPEG views and the robot's onboard camera

If the robot camera pane is blank but CCTV works, the Pi's camera topic is
not crossing the network — Stage 6 or Stage 10.

---

## Stage 12 — Full escalation run

Mark the camera spots and base spot on the Setup screen first, then trigger
a real detection (or let the scenario publisher inject one).

Watch the FSM walk the stages:

```bash
ros2 topic echo /compliance/fsm_state
```

`MONITORING -> PA_WARNING -> APPROACH -> DIRECT_WARNING -> LOGGING`

Confirm the e-stop overrides, since this is the safety path:

```bash
ros2 topic pub --once /cmd_vel_tracker geometry_msgs/msg/Twist \
    '{linear: {x: 0.0}, angular: {z: 0.0}}'
```

The tracker channel is twist_mux priority 20, above Nav2's 10. The joystick
is 100 and always wins.

---

## Stage 13 — Simulation (laptop, Gazebo Harmonic)

```bash
gz sim --version        # expect Gazebo Harmonic (8.x)
./start_sim.sh
```

**Check `/clock` first — it gates everything:**

```bash
ros2 topic hz /clock
```

Nothing else in the sim will work without it. Every node runs
`use_sim_time:=true`, so with no `/clock` they all block waiting for time to
start and the whole stack merely *appears* hung, with no error anywhere.
`/clock` comes from `ros_gz_bridge` (`yoru_base/config/gz_bridge.yaml`), and
`gz_sim` is launched with `-r` so the world runs immediately rather than
waiting for the GUI play button.

Then:

```bash
ros2 topic hz /scan /camera/image_raw /cctv1/image_raw
```

**If a topic is missing entirely**, it is a bridge problem — add it to
`gz_bridge.yaml`. Harmonic has no per-sensor ROS plugins at all; sensors
publish onto Gazebo Transport and the bridge is what carries them across.
Check the Gazebo side directly:

```bash
gz topic -l
gz topic -e -t /scan
```

**If the Gazebo side is also empty**, the world is missing the Sensors
system. Harmonic loads *nothing* implicitly — the world renders perfectly
and no camera or lidar ever produces data. Every world file now declares:

```xml
<plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
  <render_engine>ogre2</render_engine>
</plugin>
```

**If the robot renders as bare boxes** instead of the chassis mesh,
`GZ_SIM_RESOURCE_PATH` is not reaching the mesh. Harmonic ignores Classic's
`<gazebo_ros gazebo_model_path>` package.xml export; `sim.launch.py` appends
the directory instead.

**First run needs internet.** The actor skins now come from Fuel — Classic
bundled `stand.dae` and `walk.dae` locally, Harmonic does not. They cache in
`~/.gz/fuel`.

---

## Quick reference: what changed from V2

| Thing | V2 (Humble / Pi 4) | V3 (Jazzy / Pi 5) |
|---|---|---|
| Motor command topic | `/diff_cont/cmd_vel_unstamped` | `/cmd_vel_mux` |
| Lidar port | USB by-path (Pi 4 PCIe address) | `/dev/rplidar` udev symlink |
| Arduino port | by-id (board serial number) | `/dev/arduino` udev symlink |
| GPIO library | `RPi.GPIO` | `lgpio` (RP1 needs the char device) |
| pip installs | `pip3 install --user` | venv at `~/yoru_venv` (PEP 668) |
| Simulator | Gazebo Classic | Gazebo Harmonic + `ros_gz` |
| Sim sensor plumbing | per-sensor ROS plugins | `ros_gz_bridge` |
| slam_toolbox | plain Node | LifecycleNode (configure + activate) |
| Pi camera | apt `camera-ros` | source build vs RPi libcamera fork |

---

## When something is wrong and you cannot tell where

Work upward from the data, not downward from the symptom:

```bash
ros2 topic hz /scan          # sensor alive?
ros2 run tf2_ros tf2_echo odom base_link    # TF alive?
ros2 topic hz /odom          # odometry alive?
ros2 lifecycle get /slam_toolbox            # SLAM actually active?
ros2 topic hz /cmd_vel /cmd_vel_mux         # commands reaching the motors?
ros2 node list               # anything missing that should be there?
```

A node that appears in `ros2 node list` is **not** evidence it is working —
that is the lesson of both the slam_toolbox lifecycle change and the
twist_mux type mismatch. Check for data on topics, and check lifecycle
states, not process existence.
