cat <<"EOF" > /tmp/install_autostart.sh
#!/bin/bash

CURRENT_VERSION="V1"
MENU_LAUNCHER="/emulator/menu_launcher.sh"
TEMP_OUTPUT="/tmp/menu_launcher_output.sh"

NEW_AUTOSTART_CODE="\
# AUTOSTART ${CURRENT_VERSION} START\\
for i in \$(seq 1 10); do\\
  if mount | grep -q /media/usb0; then\\
    break\\
  fi\\
  sleep 1\\
done\\
\\
if [ -d /media/usb0/autostart ]; then\\
  cp -R /media/usb0/autostart /tmp/\\
  chmod +x /tmp/autostart/*.sh\\
  for f in \$(ls /tmp/autostart/*.sh); do \$f; done\\
fi\\
# AUTOSTART ${CURRENT_VERSION} END
"

if [ "$(/usr/bin/id -u)" -ne "0" ]; then
  echo "Root access required."
  exit 1
fi

export PATH=/usr/sbin:/usr/bin:/sbin:/bin

if grep -q "# AUTOSTART ${CURRENT_VERSION} START" "$MENU_LAUNCHER"; then
  echo "AUTOSTART ${CURRENT_VERSION} is already installed."
  exit 0
fi

IS_REPLACEMENT=false

# Check for Legacy V0 (unversioned)
if grep -q '# AUTOSTART BEGIN' "$MENU_LAUNCHER"; then
    OLD_START_MARKER="# AUTOSTART BEGIN"
    OLD_END_MARKER="# AUTOSTART END"
    echo "Found Legacy V0 AUTOSTART block. Removing..."
    IS_REPLACEMENT=true

# Check for any numbered version (V1, V2, etc.)
elif grep -E -q '# AUTOSTART V[0-9]+ START' "$MENU_LAUNCHER"; then
    OLD_START_MARKER=$(grep -E '# AUTOSTART V[0-9]+ START' "$MENU_LAUNCHER" | head -1)
    OLD_END_MARKER=$(echo "$OLD_START_MARKER" | sed 's/ START/ END/')
    echo "Found existing version: $OLD_START_MARKER. Removing..."
    IS_REPLACEMENT=true
fi

BACKUP_FILE="/userdata/menu_launcher.sh.bak.$(date '+%Y_%m_%d_%H_%M_%S')"
cp "$MENU_LAUNCHER" "$BACKUP_FILE"
mount -o remount,rw /emulator

PREP_SUCCESS=false
if $IS_REPLACEMENT; then
    # Delete the old block
    sed "/$OLD_START_MARKER/,/$OLD_END_MARKER/d" "$MENU_LAUNCHER" > "$TEMP_OUTPUT" && PREP_SUCCESS=true
else
    # Initial installation
    echo "No previous AUTOSTART block found. Proceeding with initial installation."
    cp "$MENU_LAUNCHER" "$TEMP_OUTPUT" && PREP_SUCCESS=true
fi

if ! $PREP_SUCCESS; then
    echo "Error: Cannot proceed with installation."
    exit 1
fi

INSTALL_SUCCESS=false

if grep -q '/emulator/atg_lcdboard' "$TEMP_OUTPUT"; then
    sed -i "/^\/emulator\/atg_lcdboard/i $NEW_AUTOSTART_CODE" "$TEMP_OUTPUT" && INSTALL_SUCCESS=true
elif grep -q '^while [ 1 -eq 1 ]' "$TEMP_OUTPUT"; then
    sed -i "/^while \[ 1 -eq 1 \]/i $NEW_AUTOSTART_CODE" "$TEMP_OUTPUT" && INSTALL_SUCCESS=true
fi

if $INSTALL_SUCCESS; then
    chmod +x "$TEMP_OUTPUT" && mv "$TEMP_OUTPUT" "$MENU_LAUNCHER"
    sync
    echo "AUTOSTART ${CURRENT_VERSION} installed successfully."
else
    echo "Error: Could not find a suitable insertion point in $MENU_LAUNCHER."
    exit 1
fi
EOF

chmod +x /tmp/install_autostart.sh
$SUDO /tmp/install_autostart.sh

rm -f /tmp/install_autostart.sh

