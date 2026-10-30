"""Generate per-user deployment files; invoked by install.sh on the Pi."""
import os
from pathlib import Path


def unit_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def configure(project: Path, config: Path):
    runtime = config / 'trace-x'
    units = config / 'systemd/user'
    autostart = config / 'autostart'
    for directory in (runtime, units, autostart):
        directory.mkdir(parents=True, exist_ok=True)
    environment = runtime / 'runtime.env'
    if not environment.exists():
        environment.write_text('ADS_MODE=simulation\nADS_SERVE_DASHBOARD=1\nADS_DATABASE_PATH=diagnostics.db\nADS_LIVE_SERIAL_PORT=\n')
    unit = f'''[Unit]
Description=Trace-X local diagnostic dashboard

[Service]
Type=simple
WorkingDirectory={unit_quote(project)}
EnvironmentFile={unit_quote(environment)}
ExecStart={unit_quote(project / '.venv-pi/bin/python')} -m uvicorn api.main:app --host 127.0.0.1 --port 13115 --workers 1
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=default.target
'''
    (units / 'trace-x.service').write_text(unit)
    # Desktop entry Exec has its own quoting rules; percent escaping still applies.
    launcher = unit_quote(project / 'deploy/pi/kiosk.sh')
    (autostart / 'trace-x.desktop').write_text(f'''[Desktop Entry]
Type=Application
Name=Trace-X Diagnostic Station
Exec=/bin/bash {launcher}
Terminal=false
X-GNOME-Autostart-enabled=true
''')


if __name__ == '__main__':
    configure(Path(os.environ['TRACE_X_PROJECT_ROOT']), Path(os.environ['TRACE_X_CONFIG_ROOT']))
