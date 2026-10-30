#!/usr/bin/env bash
# Run as the desktop user on the Pi, never with sudo.
set -euo pipefail
if [[ $(uname -s) != Linux || $(id -u) == 0 ]]; then
  echo 'Run as your normal desktop user on the Raspberry Pi (not sudo).' >&2
  exit 1
fi
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$project_root"
for dependency in python3 npm curl systemctl; do
  command -v "$dependency" >/dev/null || { echo "Missing dependency: $dependency" >&2; exit 1; }
done
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  echo 'Install Chromium before continuing.' >&2
  exit 1
fi
python3 -m venv .venv-pi
.venv-pi/bin/python -m pip install -r requirements-backend.txt
(cd frontend && npm ci && npm run build)
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
export TRACE_X_PROJECT_ROOT="$project_root" TRACE_X_CONFIG_ROOT="$config_root"
python3 deploy/pi/configure.py
systemctl --user daemon-reload
systemctl --user enable --now trace-x.service
echo 'Backend installed at http://127.0.0.1:13115/'
echo 'Launch the touchscreen with: bash deploy/pi/kiosk.sh'
echo 'See deploy/pi/README.md to enable browser autostart for your desktop.'
