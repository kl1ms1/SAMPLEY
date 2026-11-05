#!/bin/bash
# Установка SAMPLEY на Raspberry Pi OS Lite (32-bit, Bookworm и новее).
# Запуск на самой Pi:  cd SAMPLEY/software && sudo ./install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-pi}"
CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt

echo "== пакеты"
apt-get update
apt-get install -y python3-numpy python3-pil python3-spidev python3-gpiozero python3-serial \
    python3-smbus2 python3-scipy libportaudio2 fonts-dejavu-core python3-pip
pip3 install --break-system-packages sounddevice

echo "== $CONFIG"
add() { grep -qxF "$1" "$CONFIG" || echo "$1" >> "$CONFIG"; }
add "# --- SAMPLEY ---"
add "dtparam=i2c_arm=on"
add "dtparam=spi=on"
add "dtparam=i2s=on"
add "dtparam=audio=off"
add "dtoverlay=wm8960-soundcard"
add "enable_uart=1"
add "dtoverlay=gpio-poweroff,gpiopin=26,active_low=0"

echo "== UART: отдать микроконтроллеру (убрать консоль)"
raspi-config nonint do_serial_cons 1 || true
raspi-config nonint do_serial_hw 0 || true

echo "== автозапуск"
cat > /etc/systemd/system/sampley.service <<UNIT
[Unit]
Description=SAMPLEY sampler
After=sound.target

[Service]
User=$USER_NAME
WorkingDirectory=$HERE
ExecStart=/usr/bin/python3 -m sampley
Restart=on-failure
Nice=-10
LimitRTPRIO=95
SupplementaryGroups=audio gpio spi i2c dialout

[Install]
WantedBy=multi-user.target
UNIT
# кнопке питания нужно право выключать систему без пароля
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff" > /etc/sudoers.d/sampley
chmod 440 /etc/sudoers.d/sampley
systemctl daemon-reload
systemctl enable sampley

echo "Готово. Перезагрузи Pi: sudo reboot"
