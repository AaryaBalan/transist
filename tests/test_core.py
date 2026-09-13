import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from transist.core import Store, TTL, RETENTION, QUIET


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.now = 1_800_000_000.0
        self.store = Store(home=self.home, data=self.home / 'data', clock=lambda: self.now)
        with self.store.session():
            pass

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name='note.txt', content=b'valuable data'):
        path = self.store.root / name
        path.write_bytes(content)
        return path

    def tick(self):
        with self.store.session() as s:
            s.tick()
            return s.snapshot()['files']

    def expire(self):
        self.write()
        self.tick()
        self.now += TTL
        return self.tick()[0]

    def test_exact_five_hour_expiry_and_recovery_contents(self):
        path = self.write()
        self.tick()
        self.now += TTL - 1
        self.assertEqual(self.tick()[0]['status'], 'active')
        self.now += 1
        row = self.tick()[0]
        self.assertEqual(row['status'], 'deleted')
        self.assertFalse(path.exists())
        self.assertEqual((self.store.root / '.transist-recovery' / row['id']).read_bytes(), b'valuable data')

    def test_restore_resets_five_hours(self):
        row = self.expire()
        self.now += 6 * 86400
        with self.store.session() as s:
            s.action(row['id'], 'restore')
            restored = s.snapshot()['files'][0]
        self.assertEqual(restored['expires'], self.now + TTL)
        self.assertEqual(restored['status'], 'active')
        self.assertEqual((self.store.root / 'note.txt').read_bytes(), b'valuable data')

    def test_purge_at_seven_days_and_keep_history(self):
        row = self.expire()
        self.now += RETENTION - 1
        self.assertEqual(self.tick()[0]['status'], 'deleted')
        self.now += 1
        self.assertEqual(self.tick()[0]['status'], 'purged')
        self.assertFalse((self.store.root / '.transist-recovery' / row['id']).exists())
        with self.store.session() as s:
            with self.assertRaises(ValueError):
                s.action(row['id'], 'restore')

    def test_restore_rejected_after_deadline_without_purge_tick(self):
        row = self.expire()
        self.now += RETENTION
        with self.store.session() as s:
            with self.assertRaises(ValueError):
                s.action(row['id'], 'restore')

    def test_pin_then_unpin(self):
        path = self.write()
        row = self.tick()[0]
        with self.store.session() as s:
            s.action(row['id'], 'pin')
        self.now += TTL * 10
        self.assertEqual(self.tick()[0]['status'], 'active')
        self.assertTrue(path.exists())
        with self.store.session() as s:
            s.action(row['id'], 'unpin')
            self.assertEqual(s.snapshot()['files'][0]['expires'], self.now + TTL)
        self.now += TTL
        self.assertEqual(self.tick()[0]['status'], 'deleted')

    def test_collision_does_not_overwrite(self):
        row = self.expire()
        self.write(content=b'new data')
        with self.store.session() as s:
            s.action(row['id'], 'restore')
        self.assertEqual((self.store.root / 'note.txt').read_bytes(), b'new data')
        self.assertEqual(len(list(self.store.root.glob('note (restored *).txt'))), 1)

    def test_restore_avoids_symlink_collision(self):
        row = self.expire()
        outside = self.home / 'outside'
        outside.write_bytes(b'untouched')
        (self.store.root / 'note.txt').symlink_to(outside)
        with self.store.session() as s:
            s.action(row['id'], 'restore')
        self.assertEqual(outside.read_bytes(), b'untouched')
        self.assertTrue((self.store.root / 'note.txt').is_symlink())

    def test_symlinks_and_subfolders_ignored(self):
        outside = self.home / 'outside'
        outside.write_bytes(b'untouched')
        (self.store.root / 'link').symlink_to(outside)
        folder = self.store.root / 'folder'
        folder.mkdir()
        (folder / 'nested').write_text('keep')
        self.tick()
        self.now += TTL * 2
        self.assertEqual(self.tick(), [])
        self.assertEqual(outside.read_bytes(), b'untouched')
        self.assertTrue((folder / 'nested').exists())

    def test_root_symlink_rejected(self):
        other = self.home / 'other'
        self.store.root.rename(other)
        self.store.root.symlink_to(other)
        with self.assertRaises(OSError):
            with self.store.session():
                pass

    def test_recovery_symlink_rejected(self):
        vault = self.store.root / '.transist-recovery'
        vault.rmdir()
        vault.symlink_to(self.home)
        with self.assertRaises(OSError):
            with self.store.session():
                pass

    def test_hardlinks_not_expired(self):
        path = self.write()
        os.link(path, self.home / 'another-link')
        self.tick()
        self.now += TTL * 2
        self.assertEqual(self.tick()[0]['status'], 'active')
        self.assertTrue(path.exists())

    def test_changed_file_waits_until_quiet(self):
        path = self.write()
        self.tick()
        self.now += TTL
        path.write_bytes(b'writing new contents')
        self.assertEqual(self.tick()[0]['status'], 'active')
        self.now += QUIET
        self.assertEqual(self.tick()[0]['status'], 'deleted')

    def test_pause_retains_files_and_resume_expires(self):
        path = self.write()
        self.tick()
        with self.store.session() as s:
            s.configure('paused', True)
        self.now += TTL * 2
        self.assertEqual(self.tick()[0]['status'], 'active')
        self.assertTrue(path.exists())
        with self.store.session() as s:
            s.configure('paused', False)
        self.assertEqual(self.tick()[0]['status'], 'deleted')

    def test_pause_also_retains_recovery(self):
        row = self.expire()
        with self.store.session() as s:
            s.configure('paused', True)
        self.now += RETENTION
        self.assertEqual(self.tick()[0]['status'], 'deleted')
        self.assertTrue((self.store.root / '.transist-recovery' / row['id']).exists())

    def test_replacement_gets_new_timer_and_not_old_pin(self):
        path = self.write()
        row = self.tick()[0]
        with self.store.session() as s:
            s.action(row['id'], 'pin')
        replacement = self.home / 'replacement'
        replacement.write_text('replacement')
        os.replace(replacement, path)
        self.now += 100
        active = [r for r in self.tick() if r['status'] == 'active'][0]
        self.assertNotEqual(active['id'], row['id'])
        self.assertEqual(active['permanent'], 0)
        self.assertEqual(active['expires'], self.now + TTL)

    def test_screenshot_only_new_stable_images(self):
        shots = self.home / 'Screenshots'
        shots.mkdir()
        (shots / 'old.png').write_bytes(b'old image')
        with self.store.session() as s:
            s.configure('screenshot_folder', str(shots))
            s.configure('capture_screenshots', True)
        (shots / 'new.png').write_bytes(b'new image')
        (shots / 'other.pdf').write_bytes(b'document')
        self.tick()
        self.assertTrue((shots / 'new.png').exists())
        self.now += QUIET
        self.tick()
        self.assertFalse((shots / 'new.png').exists())
        self.assertTrue((shots / 'old.png').exists())
        self.assertTrue((shots / 'other.pdf').exists())
        self.assertEqual((self.store.root / 'new.png').read_bytes(), b'new image')

    def test_capture_disable_and_reenable_baselines(self):
        shots = self.home / 'Screenshots'
        shots.mkdir()
        with self.store.session() as s:
            s.configure('screenshot_folder', str(shots))
            s.configure('capture_screenshots', True)
            s.configure('capture_screenshots', False)
        (shots / 'off.png').write_bytes(b'leave alone')
        with self.store.session() as s:
            s.configure('capture_screenshots', True)
        self.tick()
        self.now += 60
        self.tick()
        self.assertTrue((shots / 'off.png').exists())

    def test_bad_screenshot_folder_refused(self):
        with self.store.session() as s:
            for path in (self.home, self.store.root, self.store.root / '.transist-recovery'):
                with self.assertRaises(ValueError):
                    s.configure('screenshot_folder', str(path))

    def test_failed_capture_baseline_rolls_back_setting(self):
        with self.store.session() as s:
            with patch.object(s, 'capture', side_effect=PermissionError('not readable')):
                with self.assertRaises(PermissionError):
                    s.configure('capture_screenshots', True)
            self.assertFalse(s.settings()['capture_screenshots'])

    def test_capture_name_collision(self):
        shots = self.home / 'Screenshots'
        shots.mkdir()
        self.write('shot.png', b'existing')
        with self.store.session() as s:
            s.configure('screenshot_folder', str(shots))
            s.configure('capture_screenshots', True)
        (shots / 'shot.png').write_bytes(b'captured')
        self.tick()
        self.now += QUIET
        self.tick()
        self.assertEqual((self.store.root / 'shot.png').read_bytes(), b'existing')
        self.assertEqual(len(list(self.store.root.glob('shot (*.png'))), 1)

    def test_restart_keeps_deadlines(self):
        self.write()
        row = self.tick()[0]
        self.now += 100
        fresh = Store(home=self.home, data=self.home / 'data', clock=lambda: self.now)
        with fresh.session() as s:
            s.tick()
            self.assertEqual(s.snapshot()['files'][0]['expires'], row['expires'])

    def test_crash_after_link_recovers_expiry(self):
        self.write()
        self.tick()
        self.now += TTL
        with self.assertRaises(OSError):
            with self.store.session() as s:
                with patch('transist.core.os.unlink', side_effect=OSError('simulated interruption')):
                    s.tick()
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'deleted')
        self.assertFalse((self.store.root / 'note.txt').exists())

    def test_crash_after_link_recovers_restore(self):
        row = self.expire()
        with self.assertRaises(OSError):
            with self.store.session() as s:
                with patch('transist.core.os.unlink', side_effect=OSError('simulated interruption')):
                    s.action(row['id'], 'restore')
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'active')
        self.assertEqual((self.store.root / 'note.txt').read_bytes(), b'valuable data')

    def test_failed_link_preserves_source(self):
        path = self.write()
        self.tick()
        self.now += TTL
        with self.assertRaises(OSError):
            with self.store.session() as s:
                with patch('transist.core.os.link', side_effect=OSError('disk failure')):
                    s.tick()
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'active')
        self.assertEqual(path.read_bytes(), b'valuable data')

    def test_unusual_names(self):
        name = 'notes "quoted" $(no-execution) 日本語\n.txt'
        self.write(name)
        self.tick()
        self.now += TTL
        row = self.tick()[0]
        with self.store.session() as s:
            s.action(row['id'], 'restore')
        self.assertEqual((self.store.root / name).read_bytes(), b'valuable data')


if __name__ == '__main__':
    unittest.main()
