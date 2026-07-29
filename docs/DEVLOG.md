# Yoru V3 — Development Log

*Sessions 1–5 below were V2 (ROS 2 Humble, Raspberry Pi 4). Session 6 is the
port to Jazzy / Pi 5 that created this repo.*

## Session 6 — 2026-07-29 (port to ROS 2 Jazzy + Raspberry Pi 5)

New repo `Yoru_bot_V3_PI5`, seeded from V2's full history so `git blame`
still reaches the original work. V2 stays as the working Humble / Pi 4
version. **Nothing in this session has been run on hardware or in Gazebo** —
it is verified by reading, cross-checked against upstream Jazzy sources, and
every file parses (Python AST, YAML, XML). First build will surface what
static checking cannot.

### The three silent failures

These are the reason `docs/PI5_BRINGUP.md` checks for *data on topics* rather
than for processes in `ros2 node list`. In each case the process starts, the
logs look healthy, and nothing flows.

1. **`twist_mux use_stamped` defaults to `true`.** twist_mux reads the
   parameter with `get_parameter()` without declaring it, and falls back to
   `true`. The flag switches **both** its subscriptions and its publisher
   between `Twist` and `TwistStamped`. Left unset on Jazzy, twist_mux would
   have subscribed as `TwistStamped` while Nav2, the dashboard teleop and the
   FSM e-stop all publish `Twist`. ROS 2 matches topics by type, so nothing
   connects and nothing is logged: the robot ignores every velocity command
   **and the emergency stop is silently dead.** Pinned `false` in
   `twist_mux.yaml` with a comment explaining why it must not be tidied away.
   This was the single most dangerous find of the port.
2. **slam_toolbox is a LifecycleNode in Jazzy.** V2 launched
   `async_slam_toolbox_node` as a plain Node. On Jazzy that starts the
   process and it appears in `ros2 node list`, but stays `unconfigured`
   forever — no `/scan` subscription, no `/map`, no `map→odom`. A robot that
   boots perfectly and never maps anything. `online_async_launch.py` now
   drives the configure→activate transitions.
3. **Hardcoded `use_sim_time: True`** in ~15 Nav2 sections. On the real robot
   with no `/clock` publisher, Nav2 blocks waiting for time and never accepts
   a goal, logging nothing useful. Removed everywhere; the launch argument is
   now the single source of truth via `SetParameter`.

Fixing (3) had a subtle prerequisite. `RewrittenYaml` can only *add* a
missing key when given a fully qualified dotted path containing
`ros__parameters`; V2 passed the bare leaf `use_sim_time`, so with the key
gone from the YAML the rewrite would silently no-op and AMCL would run on
wall-clock time under Gazebo. Hence `SetParameter` inside a `GroupAction`
rather than a rewrite.

### Velocity chain

Jazzy's `diff_drive_controller` takes `TwistStamped` only — `use_stamped_vel`
was removed and `~/cmd_vel_unstamped` no longer exists. Leaving
`use_stamped_vel` in `my_controllers.yaml` would make `controller_manager`
refuse to load the controller.

Chosen approach: keep the whole twist_mux priority chain on plain `Twist` and
convert exactly once, at the last hop, **in simulation only**:

```
Nav2 / dashboard teleop / FSM e-stop / joystick   (Twist)
    -> twist_mux -> /cmd_vel_mux                  (Twist)
        -> [real]  arduino_driver_node            (Twist, unchanged)
        -> [sim]   twist_stamper_node -> /diff_cont/cmd_vel (TwistStamped)
```

Deliberate: the hardware path carries no message-type change at all. It is
the path that cannot be tested from a laptop and the most expensive to get
wrong. `twist_stamper_node` is written in-tree (~25 lines) rather than
depending on the third-party `twist_stamper` package.

### Gazebo Classic → Harmonic

Classic went EOL January 2025; `gazebo_ros` and `gazebo_ros2_control` were
never released for Jazzy/Noble. Every sim plugin moved:

- `gazebo_ros2_control/GazeboSystem` → `gz_ros2_control/GazeboSimSystem`
- `<sensor type="ray">`/`<ray>` → `<sensor type="gpu_lidar">`/`<lidar>`
- `libgazebo_ros_{camera,ray_sensor,diff_drive}.so` → deleted; Harmonic has
  no per-sensor ROS plugins, so `ros_gz_bridge` + `config/gz_bridge.yaml`
  carries Gazebo Transport topics onto ROS
- `spawn_entity.py` → `ros_gz_sim create`
- `GAZEBO_MODEL_PATH` → `GZ_SIM_RESOURCE_PATH` (Harmonic ignores the
  `<gazebo_ros gazebo_model_path>` export, so without this the chassis mesh
  silently fails to load and the robot renders as bare collision boxes)

Two Harmonic traps worth recording. World files must now declare their system
plugins explicitly — Harmonic loads *nothing* implicitly, and omitting the
Sensors system gives a world that renders perfectly while no camera or lidar
ever produces data. And every sensor needs `<gz_frame_id>`, or messages carry
Gazebo's scoped link name, TF cannot resolve them, and the costmaps and
slam_toolbox discard every scan.

All five worlds ported: 61 Classic Ogre material scripts converted to
explicit ambient/diffuse/specular, `model://sun` and `model://table_marble`
replaced (Classic's bundled model database does not exist in Harmonic), and
actor skins moved to Fuel URIs — so the first sim run needs internet, cached
thereafter in `~/.gz/fuel`.

Also fixed a latent bug in `two_room_world.world`: the layout diagram drew
walls with hyphens, and `--` is illegal inside an XML comment. Classic's
lenient parser accepted it; a strict parser rejects the file at line 7.

### Nav2 / Jazzy API

- `progress_checker_plugin` → `progress_checker_plugins` (renamed **and**
  retyped string → vector<string>; the old key is ignored silently, leaving
  the controller with no progress checker)
- `bt_navigator`: dropped V2's 45-line `plugin_lib_names` list — Jazzy
  populates built-ins implicitly and several of those names no longer
  resolve — added the required `navigators` key and `error_code_names`
- plugin names `pkg/Type` → `pkg::Type` for the planner and all behaviors
- dropped the `bt_navigator_navigate_*_rclcpp_node` sections
- `behavior_server`: `costmap_topic`/`footprint_topic` split into `local_`
  and `global_` variants
- `LaunchConfigurationEquals` → `IfCondition(EqualsSubstitution(...))`

Kept **DWB**, not Jazzy's new MPPI default: the critic weights and
`sim_time` 1.7 were tuned against this chassis on carpet, and switching would
mean redoing that from scratch. All other navigation tuning is unchanged.

`navigation_launch.py` was minimally ported rather than replaced with
upstream's Jazzy copy, which adds `route_server`, `collision_monitor` and
`docking_server` to `lifecycle_nodes`. The lifecycle manager requires every
listed node to reach `active` or the whole bringup aborts, so adopting it
would make the robot depend on `nav2_route` and `opennav_docking` for servers
it never uses — and would have discarded the delayed-lifecycle-manager and
bond hardening fix from `0fea4fb`. Kept `velocity_smoother`'s
`cmd_vel_smoothed → cmd_vel` remap too: upstream leaves it alone because its
collision_monitor republishes `cmd_vel`, and this robot has no
collision_monitor, so without the remap nothing reaches twist_mux.

### Raspberry Pi 5 platform

- **`RPi.GPIO` cannot work.** It maps the SoC's peripheral registers through
  `/dev/mem`, but the Pi 5's header GPIOs belong to the RP1 southbridge, so
  those registers are not there. `l298n_driver_node` ported to `lgpio`
  (`tx_pwm`, `gpio_claim_alert` + `lgpio.callback` with its
  `(chip, gpio, level, timestamp)` signature, callback handles held on the
  node so they are not garbage collected). `destroy_node` now zeroes both PWM
  channels **before** closing the chip — releasing the chip first leaves the
  L298N holding the last latched duty and the robot drives away during
  shutdown. Added gpiochip autodetection via the sysfs `pinctrl-*` label,
  since older Pi 5 kernels exposed the header as `gpiochip4` rather than
  `gpiochip0`.
- Still a reference implementation, not a recommendation: lgpio's PWM is
  software timed so duty jitters with load, and encoder edges arrive as
  userspace callbacks so the Pi misses counts under load — and missed counts
  corrupt odometry silently.
- **udev symlinks** `/dev/rplidar`, `/dev/arduino`. V2's lidar port was a USB
  by-path string encoding the *Pi 4's* PCIe controller address, which does not
  exist on a Pi 5; the driver exited at startup.
- **PEP 668**: `pip3 install --user` now fails on Ubuntu 24.04. piper-tts
  moved to a venv at `~/yoru_venv` that `start_robot.sh` puts on `PYTHONPATH`
  rather than activating, so the system `rclpy` and `cv_bridge` stay visible.
- **Pi camera is the most fragile part.** Ubuntu's apt libcamera is the
  *upstream* build and ships no Raspberry Pi pipeline handlers. The Pi 5 needs
  `rpi/pisp`, whose ISP differs entirely from the Pi 4's `rpi/vc4`, so
  `ros-jazzy-camera-ros` from apt reports `no cameras available` however
  correct the ribbon cable and config.txt are. `setup_pi_camera.sh` builds
  Raspberry Pi's libcamera fork and camera_ros against it in `~/camera_ws`
  via `colcon-meson`, with pinned refs, and removes the apt package if
  present. `camera:=usb` remains the escape hatch — the onboard camera only
  feeds evidence close-ups and the dashboard, not the YOLO pipeline.
- Documented the **27 W PD supply** requirement: on a non-PD supply the Pi 5
  caps USB current at 600 mA, which will not carry lidar + Arduino + speaker.
  Brown-outs mimic software bugs (scan dropouts, phantom spikes, serial
  resyncs), so `vcgencmd get_throttled` is now step one of debugging.

### Repo hygiene

- `.gitattributes` forcing LF. The repo is edited on Windows and run on
  Linux; without it the Pi receives CRLF shell scripts and bash fails on them.
- Corrected the README's `enc_counts_per_rev` 1965 and `wheel_radius`
  0.0325 m, stale since the rewheel in `aed6a10`. The code has said 1320 and
  0.0435 m (87 mm wheels) throughout. That constant scales every distance the
  robot believes it travelled, so a wrong value in the docs is worse than
  cosmetic.
- Removed `launch_sim.launch.py` (unreferenced Classic duplicate of
  `sim.launch.py`, left over from the original tutorial) and
  `gazebo_params.yaml` (configured Classic's ROS plugin publish rate; no
  Harmonic equivalent).

### Next steps

1. **Build on the Pi**: `./deploy_to_pi.sh` then work
   `docs/PI5_BRINGUP.md` top to bottom. Expect the first colcon build to
   surface missing rosdeps.
2. **Verify `enc_counts_per_rev` 1320 with a controlled 1 m test.** Never
   confirmed; hand-rotation readings disagreed badly across sessions.
3. **Sim smoke test** on the laptop: `/clock` first, then `/scan` and the
   camera topics, then a Nav2 goal.
4. Re-mark camera and base spots — old spots hold coordinates in the old
   map's frame.

## Session 5 — 2026-07-09 (vape-aware specialist model trained + deployed)

- **Dataset** (user required Roboflow, rejected Kaggle): three CC BY 4.0
  Roboflow Universe sets merged into `datasets/smoking_vape_v1` — 18,905
  train images, classes cigarette/vape_device/smoke_vapour (tiara's "asap"
  class = Indonesian for smoke → smoke_vapour). Full citations, remapping,
  manual label audit (34/36 correct) and metrics in docs/DATASETS.md.
- **Training**: YOLOv8n, 49 epochs on the RTX 3050 Ti (paused/resumed once
  at user request). Test mAP50 0.832 (cigarette 0.821, vape_device 0.843);
  valid vape_device 0.916. ~4.5 ms/frame GPU inference.
- **Deployed**: best.pt → `smoking_vape_yolov8.pt` as `extra_model_path`
  for both CCTV pipelines, replacing the single-class cigarette model.
  Vape at mouth is now a real escalating detection (device class
  `vape_device` in C2); interim "possible vape" hint retained as fallback.
- Weights are git-ignored (`*.pt`); regenerate by re-running training or
  copy from `runs/smoking_vape_v1/weights/best.pt`.

## Session 4 — 2026-07-09 (vape problem, GPU repair, interim soft alert)

### The vape problem

A vape at the mouth is detected by COCO as `cell phone` → `mobile_phone`,
which is a C7 confounder — so vaping not only went undetected, it actively
suppressed escalation. No config fix exists (remapping phone→vape would
false-alarm on real phone calls). Proper fix: train the planned model with
a real `vape_device` class.

### Done

- **Interim soft alert** (commit 0c80d14): phone-like object held at the
  mouth for the persistence window → amber "possible vape (unverified)"
  chip on the dashboard; never announces/dispatches/emails. Plus
  `confounder_override_confidence` (0.75): a high-confidence specialist
  cigarette detection is no longer blocked by a phone/pen near the face.
- **NVIDIA driver repaired**: root cause was Ubuntu HWE kernel 6.8 needing
  gcc-12 while system gcc was 11 → nvidia-dkms-580 module build failed →
  userspace 580.159 vs old loaded module 580.95 mismatch. Fix: gcc-12
  installed and made default (update-alternatives), DKMS rebuilt +
  installed, reboot. Verified: nvidia-smi OK, torch.cuda available
  (RTX 3050 Ti, 4GB, CUDA 13.0). Detection restored to 5 fps per camera
  (was lowered to 3 for CPU).

### Next (in progress)

Train the 3-class specialist (`cigarette`, `vape_device`, `smoke_vapour`)
on the RTX 3050 Ti using public datasets, replacing cigarette_yolov8.pt
as `extra_model_path`. Then vape at mouth = real escalation.

## Session 3 — 2026-07-09 (PA announcements, second CCTV, map colors)

### Fixed / built

- **Silent PA root cause**: discovery routed through the robot's FastDDS
  server, so with the Pi off the laptop's nodes never discovered each
  other. `start_server.sh` now falls back to local discovery when the
  robot is unreachable ("STANDALONE mode"); sim mode is always local.
- **Voice**: espeak-ng installed → announcements are dynamic (speak the
  camera name); pa/direct mp3 regenerated with the V2 message (gTTS) as
  fallback. **Test Announcement button** on the dashboard Control screen
  exercises the real PA path and reports listening audio nodes.
- **Second CCTV**: Logitech C920 (/dev/video2) as full cctv2 pipeline —
  dual-model YOLO, confirmation (room `camera_2`), FSM/emailer/camera-spot
  wiring, live view on the Cameras screen (3 feeds). Both cameras
  confirmed working live. process_hz 5→3 per camera (CPU ~8→~5 cores).
- **Map colors**: dashboard map renders walls/edges white, ground grey.

### Notes

- Old leaked PAT finally revoked; new fine-grained token in gh
  (`~/.config/gh/hosts.yml`). Ubuntu's gh 2.4.0 credential helper doesn't
  feed git, so pushes use the token explicitly.
- Pre-existing broken `nvidia-driver-580` dpkg state on the laptop (also
  why YOLO runs on CPU) — untouched, fix someday.
- **Pi is stale**: re-run `./deploy_to_pi.sh` before the next robot
  session (needs sessions 3 changes).

### Next steps

1. Map the real room (robot + laptop), mark `cctv1` and `cctv2` spots.
2. Full hardware escalation test with both cameras.
3. Polish: email/incident status in dashboard, unique admin password,
   6-class model training.

## Session 2 — 2026-07-07 (real hardware bring-up on the Pi)

### Hardware as actually wired (differs from V1 plan)

Pi 4 ── ribbon ── HQ Camera (IMX477); USB ── RPLIDAR A1 (CP2102, ttyUSB0);
USB ── **Arduino Nano Every** (ttyACM0) ── L298N ── motors + quadrature
encoders. Wiring follows the ROSArduinoBridge standard map (same as
github.com/sushanthsujeerkumar/Astra_Real_robot). Wheels Ø65mm × 25mm,
track 32cm (measured).

### What was built

- **firmware/yoru_motor_bridge/**: ROSArduinoBridge port for the Nano
  Every (ATmega4809) — the stock ATmega328 PCINT encoder ISRs replaced
  with attachInterrupt(); same 57600-baud e/m/o/r/u protocol, onboard
  PID @30Hz, 2s auto-stop. Flash from the Pi:
  `arduino-cli compile|upload -b arduino:megaavr:nona4809` (arduino-cli
  in ~/.local/bin).
- **arduino_driver_node** (yoru_core): serial bridge replacing the GPIO
  l298n_driver_node in real_robot.launch.py; same topic contract
  (twist_mux output in, /odom + TF out), kinematics + odometry on the Pi.
- Encoder polarity fixed in firmware (forward was counting negative on
  both sides — bench-verified with single-wheel pulses).
- **enc_counts_per_rev = 1965**, re-measured by hand-rotating the wheels
  one revolution (left 1959 / right 1977; an earlier session measured
  ~3166 — first hand-turns were over-rotated; ≈11PPR × 4 × ~45:1 gearbox).
- Configs updated to measured chassis: wheel_radius 0.0325, separation
  0.32 (yoru_real.yaml, xacro, sim controller + gazebo diff_drive).

### Verified working (2026-07-07, on the robot)

/scan 6.8Hz, /camera/image_raw 17.3Hz (IMX477 via camera_ros), /odom
17.6Hz, slam_toolbox mapping, Nav2 up. Drive test via cmd_vel_joy:
0.1m/s for 2s → odom +0.233m, lateral drift 0.25mm.

### Next steps

1. Map the real room: laptop `./start_server.sh`, dashboard Setup screen,
   drive around, Save Map, mark the camera spot.
2. Re-check camera calibration warning (no imx477 yaml — harmless, but
   calibrate if the detector needs undistorted frames).
3. Full hardware escalation test (CCTV smoking → PA → robot dispatch).

## Session 1 — 2026-07-02 (project built from zero to working sim + real detection)

### What was decided

- **Yoru V2 = rebuild of V1** (`~/dock_ws` / github.com/deshwind/yoru_robot, the
  MSc dissertation robot). Reuse V1's proven core, put the new effort into a
  GUI-driven workflow. **~/dock_ws stays untouched.**
- **Web dashboard** (not a desktop app) is the admin GUI.
- Robot navigates to the **marked camera spot** (clicked on the map in the
  dashboard), replacing V1's pixel→map homography calibration.
- Hardware unchanged from V1: Pi 4, L298N + encoders, RPLIDAR, Pi Camera,
  speaker, PS4 pad.

### What was built

- Packages renamed/copied: `dockbot→yoru_base`, `compliance_core→yoru_core`,
  `compliance_bringup→yoru_bringup`.
- **camera_target_node** (new): confirmed smoking events resolve to the
  camera's marked pose from `maps/cameras.json` (hot-reloaded on change).
- **Dashboard V2**: first-run admin password setup (PBKDF2 hash in
  `data/admin.json`, nothing in configs), Setup screen (WASD keyboard teleop,
  Save Map button, click-to-mark camera spots), Cameras screen (live YOLO
  debug view + robot camera), plus V1's Control/Map/History.
- **Audio split**: laptop (`pa_audio_node`) speaks the PA announcement;
  robot (`robot_audio_node`) speaks the close-range final warning.
- **Launches**: `sim_full.launch.py` (one command), `sim.launch.py`
  (robot-side sim), `real_robot.launch.py` (Pi), `server.launch.py`
  (laptop, `sim:=true` to pair with sim). `mode:=auto` boots mapping until
  `maps/main_map.yaml` exists, then localization.
- **Scripts**: `start_sim.sh` (one command; `robot` arg = robot-side only),
  `start_server.sh [sim]`, `start_robot.sh` (Pi), `deploy_to_pi.sh`,
  `setup_pi.sh`, `connect_pi.sh`, `secrets.env(.example)`.
- **Dual-model detection**: YOLO node runs stock `yolov8n.pt` (persons) +
  `cigarette_yolov8.pt` (from `~/src3/models`, single class 'cigarette') on
  the same frame, merged into one detection array. Wired into
  `yoru_real.yaml` (laptop webcam = CCTV 1).

### Bugs found and fixed along the way

| Bug | Root cause | Fix |
|---|---|---|
| Robot invisible in Gazebo (only wheels/lidar) | `GAZEBO_MODEL_PATH` was hardcoded to dock_ws in `.bashrc`; V2 mesh unreachable | `gazebo_ros` export in `yoru_base/package.xml` |
| Login/setup screens ping-pong | Background polls fired before auth; every 401 forced the sign-in screen | Polls run only in-app; 401 only bounces when in-app |
| Robot drives through walls | Chassis collision was the decorative STL trimesh (ODE trimesh contacts unreliable) | Box collision; verified by driving into the east wall (pinned at x=5.81 vs wall face 5.92) |
| Whole launch aborts on URDF | launch parsed robot_description as YAML; any ": " kills it | `ParameterValue(value_type=str)` in rsp.launch.py |
| No incident email | No Gmail app password configured (V1's leaked one deliberately dropped) | New app password in git-ignored `secrets.env`; SMTP verified + test email delivered |

### Security actions

- V1's Gmail app password was hardcoded in a **public** repo → replaced by
  `COMPLIANCE_EMAIL_PASSWORD` env var via `secrets.env` (git-ignored).
- Admin password is a salted PBKDF2 hash created on first run
  (currently set to the V1 default — change before demos).
- GitHub fine-grained PAT was pasted in chat and used for the initial push —
  **must be revoked** (GitHub → Settings → Developer settings).

### Verified working (2026-07-02)

Simulation end-to-end: mapping → Save Map → mark camera spots → relaunch →
smoking scenario → PA announcement → robot drives to the cctv1 spot →
direct warning → incident logged + evidence email. Dual-model detection
verified on a test video. Repo pushed to github.com/deshwind/Yoru_bot_V2.

### Next steps (priority order)

1. **Live webcam test** of real cigarette detection: `./start_server.sh`,
   Cameras screen, cigarette near mouth → PA fires. Tune
   `extra_confidence_threshold` / `persistence_frames` if needed.
2. **Real robot bring-up**: `./connect_pi.sh` → `setup_pi.sh` →
   `./deploy_to_pi.sh` → map a real room → mark the real camera spot →
   full hardware escalation. Check L298N pins, RPLIDAR port, Pi cam overlay.
3. Polish: dashboard email/incident status, change admin password, battery
   publisher on the Pi (or drop the field), optional visual mesh rescale,
   second camera via RTSP, train the full 6-class model
   (`src/yoru_core/training/`).
