import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import install


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
            keep.parent.mkdir()
            keep.write_text('keep me')
            old_path = sys.path[:]
            try:
                with patch.dict(os.environ, env), patch.object(Path, 'home', return_value=home), patch('os.geteuid', return_value=1000), patch.object(sys, 'argv', ['install.py', '--no-service']), contextlib.redirect_stdout(io.StringIO()):
                    install.main()
                launcher = home / '.local/bin/transist'
                result = subprocess.run([str(launcher), 'status'], env={**os.environ, **env}, capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(result.stdout)['folder'], str(home / '_transist'))
                self.assertIn('service', json.loads(result.stdout))
                self.assertFalse(desktop.exists())
                self.assertFalse(old_gui.exists())
                self.assertFalse(old_theme.exists())
                self.assertEqual(keep.read_text(), 'keep me')
                unit = home / '.config/systemd/user/transist.service'
                self.assertIn('ExecStart="' + str(launcher) + '" daemon', unit.read_text())
                self.assertTrue((home / '.local/share/gnome-shell/extensions' / install.UUID / 'extension.js').is_file())
                with patch.dict(os.environ, env), patch.object(Path, 'home', return_value=home), patch('os.geteuid', return_value=1000), patch.object(sys, 'argv', ['install.py', '--uninstall']), patch('subprocess.run') as run, contextlib.redirect_stdout(io.StringIO()):
                    install.main()
                self.assertEqual(keep.read_text(), 'keep me')
                self.assertTrue((home / '.local/share/transist/state.sqlite3').is_file())
                self.assertFalse(launcher.exists())
                self.assertFalse(unit.exists())
            finally:
                sys.path[:] = old_path


if __name__ == '__main__':
    unittest.main()
