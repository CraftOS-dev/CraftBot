# Start from the exact image you were using
FROM lscr.io/linuxserver/webtop:ubuntu-xfce

# Set environment to non-interactive to avoid apt prompts
ENV DEBIAN_FRONTEND=noninteractive

# --- INSTALLATION STEPS (UNCHANGED) ---
RUN \
  echo "**** install system dependencies ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    python3-full \
    python3-pip \
    python3-tk \
    scrot \
    # Add x11-xserver-utils to ensure xrandr is present
    x11-xserver-utils && \
  echo "**** install python packages ****" && \
  # We use --break-system-packages because we are adding to the container's system python
  pip3 install --no-cache-dir \
    Pillow && \
  echo "**** cleanup ****" && \
  apt-get clean && \
  rm -rf \
    /tmp/* \
    /var/lib/apt/lists/* \
    /var/tmp/*

# --- NEW FIX: FORCE 1:1 SCALING VIA XDG AUTOSTART ---

# 1. Create the script that does the actual work.
# We add 'sleep 5' to give the X server time to initialize fully.
# We explicitly set DISPLAY=:1 which is standard for this container.
RUN echo "#!/bin/sh\n\
sleep 5\n\
export DISPLAY=:1\n\
echo 'Attempting to force 1x1 scale...'\n\
xrandr --output default --scale 1x1\n\
" > /usr/local/bin/force-1x1-scale.sh && \
chmod +x /usr/local/bin/force-1x1-scale.sh

# 2. Create a .desktop entry that tells Xfce to run that script on startup.
# Placing it in /etc/xdg/autostart makes it run for the user session.
RUN echo "[Desktop Entry]\n\
Type=Application\n\
Name=Force 1x1 Scale\n\
Comment=Ensure 1:1 pixel mapping for automation\n\
Exec=/usr/local/bin/force-1x1-scale.sh\n\
StartupNotify=false\n\
Terminal=false\n\
Hidden=false" > /etc/xdg/autostart/force-scale.desktop