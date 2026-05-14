#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ "${EUID}" -ne 0 ]]; then
  # Avoid relying on `sudo -E` (may be disabled by policy).
  exec sudo "$0" "$@"
fi

SYSTEM_SERVICE="input-remapper.service"
WINDOWD_USER_SERVICE="input-remapper-windowd.service"

echo "==> Installing input-remapper from source checkout:"
echo "    $repo_root"

echo "==> Ensuring system dependencies (PyGObject / GTK introspection)"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    python3-gi python3-gi-cairo python3-cairo \
    gir1.2-gtk-3.0 gir1.2-gtksource-4
else
  echo "!! apt-get not found; please ensure PyGObject is installed (python3-gi)"
fi

echo "==> Stopping system service (if running): ${SYSTEM_SERVICE}"
systemctl stop "${SYSTEM_SERVICE}" >/dev/null 2>&1 || true

echo "==> Installing python module + data files to /"
python3 -m install --root /

echo "==> Verifying python dependencies"
python3 install/check_dependencies.py || true

echo "==> Reloading systemd units"
systemctl daemon-reload

echo "==> Restarting system service: ${SYSTEM_SERVICE}"
systemctl restart "${SYSTEM_SERVICE}"

echo "==> Reloading udev rules"
udevadm control --reload-rules || true
udevadm trigger || true

if [[ -n "${SUDO_USER:-}" ]]; then
  user="${SUDO_USER}"
  uid="$(id -u "${user}")"
  runtime_dir="/run/user/${uid}"
  session_bus="unix:path=${runtime_dir}/bus"

  if [[ -S "${runtime_dir}/bus" ]]; then
    echo "==> Restarting user window daemon for ${user}: ${WINDOWD_USER_SERVICE}"
    sudo -u "${user}" \
      XDG_RUNTIME_DIR="${runtime_dir}" \
      DBUS_SESSION_BUS_ADDRESS="${session_bus}" \
      systemctl --user restart "${WINDOWD_USER_SERVICE}" >/dev/null 2>&1 || true
  else
    echo "==> Skipping ${WINDOWD_USER_SERVICE} restart (no session bus at ${runtime_dir}/bus)"
  fi
fi

echo "==> Done."
