import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import install
from transist.core import Store


class InstallerTests(unittest.TestCase):
    def test_install_launcher_and_uninstall_preserve_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'a home with spaces'
            home.mkdir()
            env = {'HOME': str(home), 'XDG_DATA_HOME': str(home / '.local/share'), 'XDG_CONFIG_HOME': str(home / '.config')}
            # Simulate the old standalone-app installation, including existing files.
            desktop = home / '.local/share/applications/io.github.transist.App.desktop'
            old_gui = home / '.local/share/transist-app/transist/gui.py'
            old_theme = home / '.local/share/transist-app/transist/theme.py'
            for path in (desktop, old_gui, old_theme):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('old app')
            keep = home / '_transist/keep.txt'
            keep.parent.mkdir(mode=0o700)
            keep.write_text('keep me')
            old_path = sys.path[:]
            try:
                with patch.dict(os.environ, env), patch.object(Path, 'home', return_value=home), patch('os.geteuid', return_value=1000), patch.object(install, 'file_manager_runtime_available', return_value=True), patch.object(sys, 'argv', ['install.py', '--no-service']), contextlib.redirect_stdout(io.StringIO()):
                    install.main()
                launcher = home / '.local/bin/transist'
                result = subprocess.run([str(launcher), 'status'], env={**os.environ, **env}, capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(result.stdout)['folder'], str(home / '_transist'))
                self.assertIn('service', json.loads(result.stdout))
                result = subprocess.run([str(launcher), 'config', 'lifetime_hours', '48'], env={**os.environ, **env}, capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(result.stdout)['settings']['lifetime_hours'], 48)
                result = subprocess.run([str(launcher), 'config', 'lifetime_hours', '2'], env={**os.environ, **env}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(desktop.exists())
                self.assertFalse(old_gui.exists())
                self.assertFalse(old_theme.exists())
                self.assertEqual(keep.read_text(), 'keep me')
                unit = home / '.config/systemd/user/transist.service'
                self.assertIn('ExecStart="' + str(launcher) + '" daemon', unit.read_text())
                self.assertTrue((home / '.local/share/gnome-shell/extensions' / install.UUID / 'extension.js').is_file())
                self.assertTrue((home / '.local/share/gnome-shell/extensions' / install.UUID / 'schemas/gschemas.compiled').is_file())
                guard = home / '.local/share/nautilus-python/extensions/transist_guard.py'
                self.assertTrue(guard.is_file())
                self.assertTrue(guard.with_name('transist_guard_native.so').is_file())
                # Uninstall clears real tracked recovery bytes, but keeps active files.
                (home / '_transist/past.txt').write_text('old recovery')
                clock = [1_800_000_000]
                store = Store(home=home, data=home / '.local/share/transist', clock=lambda: clock[0])
                with store.session() as state:
                    state.tick()
                    permanent = next(r for r in state.snapshot()['files'] if r['name'] == 'keep.txt')
                    state.action(permanent['id'], 'pin')
                clock[0] += 48 * 3600
                with store.session() as state:
                    state.tick()
                    recovery = next(r for r in state.snapshot()['files'] if r['name'] == 'past.txt')
                recovery_path = home / '_transist/.transist-recovery' / recovery['id']
                self.assertTrue(recovery_path.is_file())
                with patch.dict(os.environ, env), patch.object(Path, 'home', return_value=home), patch('os.geteuid', return_value=1000), patch.object(sys, 'argv', ['install.py', '--uninstall']), patch('subprocess.run') as run, contextlib.redirect_stdout(io.StringIO()):
                    install.main()
                self.assertEqual(keep.read_text(), 'keep me')
                self.assertFalse(recovery_path.exists())
                database = home / '.local/share/transist/state.sqlite3'
                self.assertTrue(database.is_file())
                with sqlite3.connect(database) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM files').fetchone()[0], 0)
                    self.assertEqual(json.loads(db.execute("SELECT value FROM settings WHERE key='lifetime_hours'").fetchone()[0]), 48)
                self.assertFalse(launcher.exists())
                self.assertFalse(unit.exists())
                self.assertFalse(guard.exists())
                self.assertFalse(guard.with_name('transist_guard_native.so').exists())
            finally:
                sys.path[:] = old_path


if __name__ == '__main__':
    unittest.main()
