#!/usr/bin/env bash
# Pi Camera Module (IMX477 HQ camera) on Raspberry Pi 5 + Ubuntu 24.04 + Jazzy.
#
# WHY THIS SCRIPT EXISTS
# ----------------------
# On Ubuntu 24.04 the apt libcamera is the UPSTREAM build. Upstream does not
# ship Raspberry Pi's pipeline handlers, and the Pi 5 needs 'rpi/pisp' - its
# image signal processor is completely different from the Pi 4's 'rpi/vc4'.
# So `ros2 run camera_ros camera_node` installed from apt reports
#     "no cameras available"
# no matter how correct the ribbon cable and config.txt are.
#
# The fix is to build Raspberry Pi's libcamera fork and then camera_ros
# against it. Both go in a dedicated colcon workspace (~/camera_ws) that is
# chained ahead of the robot workspace, so a rebuild of the robot code can
# never trigger a 20 minute libcamera rebuild.
#
# This is the single most fragile step of the Pi 5 port. It is separated from
# setup_pi.sh so you can re-run it alone:
#     ./setup_pi_camera.sh
set -e

CAMERA_WS="$HOME/camera_ws"
# Pinned so a future upstream change cannot silently break a working robot.
# To move forward deliberately, bump these and re-run.
LIBCAMERA_REF="v0.5.0+rpt20250429"
CAMERA_ROS_REF="0.5.1"

echo "============================================================"
echo "  Pi camera stack: libcamera (RPi fork) + camera_ros"
echo "  Workspace: $CAMERA_WS"
echo "  This takes 15-25 minutes on a Pi 5. Keep it powered and cool."
echo "============================================================"
echo ""

# --- 1. Kernel-side: is the sensor even detected? --------------------------
echo ">>> 1/5  Checking the sensor is on the CSI bus ..."
if ! dmesg 2>/dev/null | grep -qi 'imx477\|imx708\|imx219\|ov5647'; then
    cat <<'EOF'
    WARNING: no camera sensor found in the kernel log.

    The Pi 5 does NOT auto-detect on Ubuntu the way Raspberry Pi OS does.
    Edit /boot/firmware/config.txt and make sure it has:

        camera_auto_detect=0
        dtoverlay=imx477            # HQ camera. imx708=v3, imx219=v2, ov5647=v1

    Note the Pi 5 has TWO camera connectors - use ",cam0" or ",cam1" to pick:
        dtoverlay=imx477,cam0

    Then REBOOT and re-run this script. Continuing anyway, but the build
    will produce a camera_node that finds nothing.
EOF
    echo ""
else
    echo "    OK - sensor detected:"
    dmesg | grep -i 'imx477\|imx708\|imx219\|ov5647' | tail -2 | sed 's/^/      /'
fi

# --- 2. Build dependencies -------------------------------------------------
echo ""
echo ">>> 2/5  Build dependencies ..."
sudo apt update
sudo apt install -y \
    git g++ cmake meson ninja-build pkg-config \
    python3-colcon-meson python3-jinja2 python3-ply python3-yaml \
    libyaml-dev libssl-dev libgnutls28-dev openssl \
    libboost-dev libdw-dev libunwind-dev libudev-dev \
    libevent-dev libdrm-dev \
    ros-jazzy-camera-info-manager ros-jazzy-cv-bridge

# Ubuntu's apt camera_ros links against the WRONG (upstream) libcamera. If it
# is installed, the ament index will prefer it over our source build and the
# problem this script exists to solve comes straight back.
if dpkg -l ros-jazzy-camera-ros 2>/dev/null | grep -q '^ii'; then
    echo ""
    echo "    Removing apt ros-jazzy-camera-ros: it links against Ubuntu's"
    echo "    upstream libcamera and would shadow this source build."
    sudo apt remove -y ros-jazzy-camera-ros
fi

# --- 3. Sources ------------------------------------------------------------
echo ""
echo ">>> 3/5  Fetching sources ..."
mkdir -p "$CAMERA_WS/src"
cd "$CAMERA_WS/src"

if [ ! -d libcamera ]; then
    git clone https://github.com/raspberrypi/libcamera.git
fi
git -C libcamera fetch --tags --quiet
git -C libcamera checkout --quiet "$LIBCAMERA_REF" 2>/dev/null || {
    echo "    NOTE: tag $LIBCAMERA_REF not found, staying on the default branch."
    git -C libcamera checkout --quiet main 2>/dev/null || true
}
echo "    libcamera  @ $(git -C libcamera describe --tags --always)"

if [ ! -d camera_ros ]; then
    git clone https://github.com/christianrauch/camera_ros.git
fi
git -C camera_ros fetch --tags --quiet
git -C camera_ros checkout --quiet "$CAMERA_ROS_REF" 2>/dev/null || {
    echo "    NOTE: tag $CAMERA_ROS_REF not found, staying on the default branch."
    git -C camera_ros checkout --quiet main 2>/dev/null || true
}
echo "    camera_ros @ $(git -C camera_ros describe --tags --always)"

# --- 4. Build --------------------------------------------------------------
# colcon-meson drives libcamera's meson build inside the colcon workspace, so
# camera_ros then finds it through the workspace rather than through
# /usr/lib. The pipeline list is explicit: rpi/pisp is the Pi 5's ISP and is
# the whole reason the apt build fails.
echo ""
echo ">>> 4/5  Building (this is the slow part) ..."
cd "$CAMERA_WS"
source /opt/ros/jazzy/setup.bash

colcon build \
    --packages-select libcamera \
    --cmake-args -DCMAKE_BUILD_TYPE=Release \
    --meson-args \
        -Dpipelines=rpi/vc4,rpi/pisp \
        -Dipas=rpi/vc4,rpi/pisp \
        -Dv4l2=true \
        -Dgstreamer=disabled \
        -Dtest=false \
        -Dlc-compliance=disabled \
        -Dcam=disabled \
        -Dqcam=disabled \
        -Ddocumentation=disabled \
        -Dpycamera=disabled

source install/setup.bash
colcon build --packages-select camera_ros --cmake-args -DCMAKE_BUILD_TYPE=Release

# --- 5. Verify -------------------------------------------------------------
echo ""
echo ">>> 5/5  Verifying ..."
source "$CAMERA_WS/install/setup.bash"

# Make the camera workspace part of every future shell, ahead of the robot
# workspace. start_robot.sh sources it too, for non-interactive SSH launches.
LINE="source $CAMERA_WS/install/setup.bash"
grep -qxF "$LINE" "$HOME/.bashrc" || echo "$LINE" >> "$HOME/.bashrc"

echo ""
echo "============================================================"
echo "  Camera stack built."
echo ""
echo "  Verify the sensor is visible to libcamera:"
echo "      ros2 run camera_ros camera_node --ros-args -p width:=640 -p height:=480"
echo ""
echo "  Expected: a log line naming your sensor, e.g."
echo "      [camera_node]: found camera /base/axi/pcie@1000120000/rp1/i2c@88000/imx477@1a"
echo "  Then, from another terminal:"
echo "      ros2 topic hz /camera/image_raw        # ~10-30 Hz"
echo ""
echo "  If it still says 'no cameras available', the sensor is not on the"
echo "  bus - that is a config.txt / ribbon-cable problem, not a build one."
echo "  Re-check step 1 above and reboot."
echo "============================================================"
