#!/usr/bin/env bash
# One-time Raspberry Pi 5 provisioning - run ON the Pi.
#
# Assumes: Ubuntu 24.04 Server arm64 + ROS 2 Jazzy base already installed
#          (per docs.ros.org/en/jazzy - the ros-jazzy-ros-base metapackage).
#
# The Pi does NOT need ultralytics or YOLO - perception runs on the server.
#
# Usage:
#   ./setup_pi.sh                 # everything, including the camera build
#   ./setup_pi.sh --no-camera     # skip the ~20 min libcamera source build
#   ./setup_pi.sh --camera-only   # rebuild just libcamera + camera_ros
set -e
cd "$(dirname "$0")"

DO_CAMERA=1
DO_BASE=1
for a in "$@"; do
    case "$a" in
        --no-camera)   DO_CAMERA=0 ;;
        --camera-only) DO_BASE=0 ;;
        *) echo "Unknown option: $a"; exit 1 ;;
    esac
done

# --- Sanity checks: fail loudly now rather than confusingly in 20 minutes ---
echo ">>> Checking platform ..."
PI_MODEL=$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)
echo "    Board:  $PI_MODEL"
case "$PI_MODEL" in
    *"Raspberry Pi 5"*) ;;
    *) echo "    WARNING: this script targets the Pi 5. For a Pi 4 use the"
       echo "             Yoru_bot_V2 repo - GPIO and USB paths differ." ;;
esac

. /etc/os-release
echo "    OS:     $PRETTY_NAME"
[ "$VERSION_ID" = "24.04" ] || \
    echo "    WARNING: expected Ubuntu 24.04 (ROS 2 Jazzy's Tier-1 platform)."

if [ ! -f /opt/ros/jazzy/setup.bash ]; then
    echo "    ERROR: /opt/ros/jazzy not found. Install ROS 2 Jazzy first:"
    echo "           https://docs.ros.org/en/jazzy/Installation.html"
    exit 1
fi
echo "    ROS:    jazzy"

if [ "$DO_BASE" = 1 ]; then

echo ""
echo ">>> apt packages (ROS drivers + tools) ..."
sudo apt update
sudo apt install -y \
    ros-jazzy-rplidar-ros \
    ros-jazzy-nav2-bringup \
    ros-jazzy-slam-toolbox \
    ros-jazzy-twist-mux \
    ros-jazzy-robot-state-publisher \
    ros-jazzy-xacro \
    ros-jazzy-cv-bridge \
    ros-jazzy-vision-msgs \
    ros-jazzy-joy \
    ros-jazzy-teleop-twist-joy \
    python3-serial \
    python3-opencv python3-numpy python3-yaml \
    python3-colcon-common-extensions python3-rosdep \
    espeak-ng alsa-utils \
    joystick bluetooth bluez

# Pi 5 GPIO: the RP1 southbridge means RPi.GPIO cannot work (it pokes SoC
# registers through /dev/mem, and the GPIO registers now live on RP1).
# lgpio drives the kernel character device instead and works on every Pi.
# Only the legacy l298n_driver_node needs this - the robot drives its
# motors through the Arduino bridge over USB serial.
echo ""
echo ">>> GPIO stack for the legacy direct-drive node (lgpio, not RPi.GPIO) ..."
sudo apt install -y python3-lgpio || {
    echo "    (python3-lgpio unavailable - l298n_driver_node stays unusable,"
    echo "     which is harmless: the Arduino bridge is the supported driver)"
}

# Ubuntu 24.04 enforces PEP 668: 'pip3 install --user' now fails with
# 'externally-managed-environment'. Anything without a Debian package goes
# into a venv that start_robot.sh puts on PYTHONPATH.
echo ""
echo ">>> Python venv for pip-only packages (PEP 668) ..."
sudo apt install -y python3-venv
VENV="$HOME/yoru_venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install --quiet piper-tts
echo "    venv ready: $VENV"

echo ""
echo ">>> Piper neural TTS voice model ..."
mkdir -p voices
for f in en_GB-alba-medium.onnx en_GB-alba-medium.onnx.json; do
    [ -f voices/"$f" ] || curl -sL -o voices/"$f" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium/$f"
done
echo "    voices/ populated"

# Stable device names. V2's launch file hardcoded a Pi 4 USB by-path string
# (platform-fd500000.pcie-...) that does not exist on a Pi 5 - its PCIe
# controller sits at a different address. udev symlinks are immune to both
# the board revision and which port something is plugged into.
echo ""
echo ">>> udev rules: /dev/rplidar and /dev/arduino ..."
sudo cp udev/99-yoru.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "    installed - replug the USB devices to pick up the symlinks"

echo ""
echo ">>> Permissions: serial, video, audio, gpio, input ..."
sudo usermod -aG dialout,video,audio,gpio,input "$USER" 2>/dev/null || \
sudo usermod -aG dialout,video,audio "$USER"

fi  # DO_BASE

if [ "$DO_CAMERA" = 1 ]; then
    echo ""
    ./setup_pi_camera.sh
fi

echo ""
echo "============================================================"
echo "  Provisioning done."
echo ""
echo "  1. Log out and back in  (group changes need a new session)"
echo "  2. Check the devices:    ls -l /dev/rplidar /dev/arduino"
echo "  3. From the laptop:      ./deploy_to_pi.sh <this-pi-ip> $USER"
echo ""
echo "  Optional - pair a PS4 pad with the Pi instead of the laptop:"
echo "      bluetoothctl -> scan on -> hold SHARE+PS -> pair/trust/connect"
echo ""
echo "  Bring-up checklist, with the expected output at every stage:"
echo "      docs/PI5_BRINGUP.md"
echo "============================================================"
