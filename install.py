#!/usr/bin/env python3
"""Per-user installation. Never requires sudo. Keeps user files on uninstall."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent
UUID = 'transist@aaryabalan.local'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-service', action='store_true', help='Install without starting cleanup')
    parser.add_argument('--no-extension', action='store_true', help='Install only the headless service and CLI')
    parser.add_argument('--uninstall', action='store_true', help='Remove program; preserve all files, recovery data, and settings')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your ordinary desktop user, without sudo.')
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required.')
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share'))
    config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    app = data / 'transist-app'
    launcher = home / '.local/bin/transist'
    unit = config / 'systemd/user/transist.service'
    desktop = data / 'applications/io.github.transist.App.desktop'
    icon = data / 'icons/hicolor/scalable/apps/io.github.transist.App.svg'
    extension = data / 'gnome-shell/extensions' / UUID
    if args.uninstall:
        if shutil.which('systemctl'):
            subprocess.run(['systemctl', '--user', 'disable', '--now', 'transist.service'], check=False)
        if shutil.which('gnome-extensions'):
            subprocess.run(['gnome-extensions', 'disable', UUID], check=False)
        for path in (launcher, unit, desktop, icon):
            path.unlink(missing_ok=True)
        for path in (app, extension):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        if shutil.which('systemctl'):
            subprocess.run(['systemctl', '--user', 'daemon-reload'], check=False)
        print('Uninstalled. _transist, recovery copies, and the history database are preserved. Cleanup has stopped.')
        return
    if not args.no_service and not shutil.which('systemctl'):
        parser.error('systemd is required for automatic startup. Use --no-service and run transist daemon with your own supervisor.')
    if not args.no_extension and not shutil.which('glib-compile-schemas'):
        parser.error('glib-compile-schemas is required to install the GNOME extension settings.')
    for path in (app, launcher.parent, unit.parent):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE / 'transist', app / 'transist', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(SOURCE / 'LICENSE', app / 'LICENSE')
    launcher.write_text('#!' + sys.executable + '\nimport sys\nsys.path.insert(0, ' + repr(str(app)) + ')\nfrom transist.__main__ import main\nmain()\n')
    launcher.chmod(0o755)
    # systemd and desktop-file values have different escaping rules.
    systemd_path = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    unit.write_text('[Unit]\nDescription=Transist temporary-file cleanup\n\n[Service]\nType=simple\nExecStart="' + systemd_path + '" daemon\nRestart=on-failure\nRestartSec=10\nUMask=0077\nNoNewPrivileges=true\n\n[Install]\nWantedBy=default.target\n')
    # Preserve custom XDG locations for the user service.
    env_lines = ''.join('Environment=' + json.dumps(k + '=' + str(v)).replace('%', '%%') + '\n' for k, v in [('XDG_DATA_HOME', data), ('XDG_CONFIG_HOME', config)])
    unit.write_text(unit.read_text().replace('Type=simple\n', 'Type=simple\n' + env_lines))
    # Remove only the obsolete app entry and known GUI sources during upgrade.
    for obsolete in (desktop, icon, app / 'transist/gui.py', app / 'transist/theme.py'):
        obsolete.unlink(missing_ok=True)
    if not args.no_extension:
        shutil.copytree(SOURCE / 'extension', extension, dirs_exist_ok=True)
        subprocess.run(['glib-compile-schemas', '--strict', str(extension / 'schemas')], check=True)
    # Initialize only after dependencies are checked.
    sys.path.insert(0, str(app))
    from transist.core import Store
    with Store().session():
        pass
    if not args.no_service:
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', '--user', 'enable', '--now', 'transist.service'], check=True)
        subprocess.run(['systemctl', '--user', 'restart', 'transist.service'], check=True)
    print('Installed the extension and headless cleanup service. No desktop app is installed.')
    if args.no_service:
        print('Cleanup is not running. Start ~/.local/bin/transist daemon when ready.')
    if not args.no_extension:
        print('For GNOME: log out and back in, then run: gnome-extensions enable ' + UUID)
    print('Open settings: gnome-extensions prefs ' + UUID)
    print('Existing settings and file history are preserved. Screenshot capture defaults to OFF for new installs.')


if __name__ == '__main__':
    main()
