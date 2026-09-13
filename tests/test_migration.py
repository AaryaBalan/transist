import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import migration
from transit.core import Store, TTL


class RenameMigrationTests(unittest.TestCase):
    def test_existing_files_recovery_settings_and_deadlines_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            data, config = home / '.local/share', home / '.config'
            old_extension = data / 'gnome-shell/extensions' / migration.OLD_UUID
            old_extension.mkdir(parents=True)
            clock = [1_800_000_000]
            old = Store(home=home, data=data / migration.OLD, clock=lambda: clock[0])
            old.root = home / ('_' + migration.OLD)
            with old.session():
                pass
            (old.root / 'keep.txt').write_text('permanent')
            (old.root / 'recover.txt').write_text('recoverable')
            with old.session() as state:
                state.tick()
                kept = next(r for r in state.snapshot()['files'] if r['name'] == 'keep.txt')
                state.action(kept['id'], 'pin')
            clock[0] += TTL
            with old.session() as state:
                state.tick()
                state.configure('lifetime_hours', 72)
                before = state.snapshot()['files']
                state.db.execute("INSERT OR REPLACE INTO lifecycle VALUES ('extension', ?)",
                                 (json.dumps(state.directory_identity(old_extension)),))
            (old.root / '.transit-recovery').rename(old.root / ('.' + migration.OLD + '-recovery'))
            with patch('migration.shutil.which', return_value='/usr/bin/tool'), patch('migration.subprocess.run'):
                migration.prepare(home, data, config)
            new_extension = data / 'gnome-shell/extensions/transit@aaryabalan.local'
            new_extension.mkdir()
            new = Store(home=home, data=data / 'transit', clock=lambda: clock[0])
            with new.session() as state:
                self.assertEqual(state.snapshot()['files'], before)
                self.assertEqual(state.settings()['lifetime_hours'], 72)
                recover = next(r for r in before if r['name'] == 'recover.txt')
                state.action(recover['id'], 'restore')
            self.assertEqual((new.root / 'recover.txt').read_text(), 'recoverable')
            self.assertEqual((new.root / 'keep.txt').read_text(), 'permanent')
            migration.finish(home, data, config)
            self.assertFalse(old_extension.exists())
            self.assertFalse(old.root.exists())
            self.assertFalse(old.data.exists())
            self.assertIsNone(migration.prepare(home, data, config))

    def test_collision_refuses_without_moving_or_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            source = home / ('_' + migration.OLD)
            source.mkdir()
            (source / 'keep.txt').write_text('old collection')
            (home / '_transit').mkdir()
            with patch('migration.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'Both'):
                migration.prepare(home, home / 'data', home / 'config')
            run.assert_not_called()
            self.assertEqual((source / 'keep.txt').read_text(), 'old collection')

    def test_direct_screenshot_setting_is_carried_forward(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            data = home / '.local/share'
            schema = data / 'gnome-shell/extensions' / migration.OLD_UUID / 'schemas/gschemas.compiled'
            schema.parent.mkdir(parents=True)
            schema.touch()
            with patch('migration.shutil.which', return_value='/usr/bin/tool'), patch('migration.subprocess.run') as run:
                run.return_value.stdout = 'true\n'
                self.assertEqual(migration.prepare(home, data, home / '.config'), 'true')
