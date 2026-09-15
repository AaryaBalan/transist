import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from transit.core import Store, TTL, RETENTION, QUIET, LIFETIME_HOURS


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
        self.assertEqual((self.store.root / '.transit-recovery' / row['id']).read_bytes(), b'valuable data')

    def test_every_cleanup_window_expires_at_its_deadline(self):
        for hours in LIFETIME_HOURS:
            with self.subTest(hours=hours):
                with self.store.session() as s:
                    s.configure('lifetime_hours', hours)
                path = self.write(f'{hours}.txt')
                rows = self.tick()
                row = next(r for r in rows if r['name'] == path.name)
                self.assertEqual(row['expires'], self.now + hours * 3600)
                self.now += hours * 3600 - 1
                self.tick()
                self.assertTrue(path.exists())
                self.now += 1
                self.tick()
                self.assertFalse(path.exists())

    def test_window_change_preserves_elapsed_time_and_recovery_deadline(self):
        deleted = self.expire()
        path = self.write('active.txt')
        row = next(r for r in self.tick() if r['name'] == path.name)
        self.now += 2 * 3600
        with self.store.session() as s:
            s.configure('lifetime_hours', 12)
            active = next(r for r in s.snapshot()['files'] if r['id'] == row['id'])
            self.assertEqual(active['expires'], row['added'] + 12 * 3600)
            s.configure('lifetime_hours', 1)
            recovery = next(r for r in s.snapshot()['files'] if r['id'] == deleted['id'])
            self.assertEqual(recovery['purge_at'], deleted['purge_at'])
        self.tick()
        self.assertFalse(path.exists())

    def test_selected_window_survives_restart_and_applies_to_restore_and_unpin(self):
        deleted = self.expire()
        with self.store.session() as s:
            s.configure('lifetime_hours', 72)
        fresh = Store(home=self.home, data=self.home / 'data', clock=lambda: self.now)
        with fresh.session() as s:
            self.assertEqual(s.settings()['lifetime_hours'], 72)
            s.action(deleted['id'], 'restore')
            self.assertEqual(s.snapshot()['files'][0]['expires'], self.now + 72 * 3600)
            s.action(deleted['id'], 'pin')
            pinned_deadline = s.snapshot()['files'][0]['expires']
            s.configure('lifetime_hours', 1)
            self.assertEqual(s.snapshot()['files'][0]['expires'], pinned_deadline)
        self.now += 4 * 3600
        self.assertEqual(self.tick()[0]['status'], 'active')
        with self.store.session() as s:
            s.action(deleted['id'], 'unpin')
            self.assertEqual(s.snapshot()['files'][0]['expires'], self.now + 3600)
        start = self.now
        self.now += 1800
        with self.store.session() as s:
            s.configure('lifetime_hours', 5)
            self.assertEqual(s.snapshot()['files'][0]['expires'], start + TTL)
            s.configure('lifetime_hours', 5)
            self.assertEqual(s.snapshot()['files'][0]['expires'], start + TTL)

    def test_window_change_while_paused_defers_removal_until_resume(self):
        path = self.write()
        self.tick()
        self.now += 2 * 3600
        with self.store.session() as s:
            s.configure('paused', True)
            s.configure('lifetime_hours', 1)
        self.tick()
        self.assertTrue(path.exists())
        with self.store.session() as s:
            s.configure('paused', False)
        self.tick()
        self.assertFalse(path.exists())

    def test_invalid_windows_leave_setting_and_deadlines_unchanged(self):
        self.write()
        row = self.tick()[0]
        with self.store.session() as s:
            for value in (0, -1, 2, 169, True, 1.0, '12', None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    s.configure('lifetime_hours', value)
            self.assertEqual(s.settings()['lifetime_hours'], 5)
            self.assertEqual(s.snapshot()['files'][0]['expires'], row['expires'])

    def test_manual_delete_is_recoverable_even_if_permanent_and_paused(self):
        path = self.write()
        row = self.tick()[0]
        with self.store.session() as state:
            state.action(row['id'], 'pin')
            state.configure('paused', True)
            state.action(row['id'], 'delete')
            deleted = state.snapshot()['files'][0]
            self.assertEqual(deleted['status'], 'deleted')
            self.assertEqual(deleted['purge_at'], self.now + RETENTION)
            self.assertFalse(path.exists())
            preview = state.recovery_path(row['id'])
            self.assertEqual(Path(preview['path']).read_bytes(), b'valuable data')
            self.assertEqual(preview['name'], 'note.txt')
            state.action(row['id'], 'restore')
        self.assertEqual(path.read_bytes(), b'valuable data')

    def test_delete_refuses_replaced_file(self):
        path = self.write()
        row = self.tick()[0]
        path.rename(self.home / 'original')
        path.write_text('replacement')
        with self.store.session() as state, self.assertRaisesRegex(ValueError, 'no longer active'):
            state.action(row['id'], 'delete')
        self.assertEqual(path.read_text(), 'replacement')

    def test_empty_trash_clears_history_and_recovery_only(self):
        deleted = self.expire()
        active = self.write('keep.txt')
        self.tick()
        system_trash = self.home / '.local/share/Trash/files'
        system_trash.mkdir(parents=True)
        (system_trash / 'untouched').write_text('keep')
        with self.store.session() as state:
            state.empty_trash()
            self.assertEqual([r['name'] for r in state.snapshot()['files']], ['keep.txt'])
            state.empty_trash()
        self.assertTrue(active.exists())
        self.assertFalse((self.store.root / '.transit-recovery' / deleted['id']).exists())
        self.assertEqual((system_trash / 'untouched').read_text(), 'keep')

    def test_preview_rejects_expired_or_replaced_recovery(self):
        deleted = self.expire()
        self.now = deleted['purge_at']
        with self.store.session() as state, self.assertRaises(ValueError):
            state.recovery_path(deleted['id'])
        self.now -= 1
        path = self.store.root / '.transit-recovery' / deleted['id']
        path.rename(self.home / 'original')
        path.symlink_to(self.home / 'original')
        with self.store.session() as state:
            with self.assertRaises(ValueError):
                state.recovery_path(deleted['id'])
            state.empty_trash()
            self.assertEqual(state.snapshot()['files'], [])
        self.assertTrue(path.is_symlink())
        self.assertEqual((self.home / 'original').read_bytes(), b'valuable data')

    def test_restore_resets_five_hours(self):
        row = self.expire()
        self.now += 6 * 86400
        with self.store.session() as s:
            s.action(row['id'], 'restore')
            restored = s.snapshot()['files'][0]
        self.assertEqual(restored['expires'], self.now + TTL)
        self.assertEqual(restored['status'], 'active')
        self.assertEqual((self.store.root / 'note.txt').read_bytes(), b'valuable data')

    def test_deleted_root_starts_fresh_without_unavailable_history(self):
        self.expire()
        self.write('active.txt')
        self.tick()
        shutil.rmtree(self.store.root)
        with self.store.session() as s:
            self.assertFalse(s.storage_recreated)
            self.assertEqual(s.snapshot()['files'], [])
            self.assertEqual(s.snapshot()['missing_recovery_count'], 0)
        self.write('new.txt')
        row = self.tick()[0]
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['id'], row['id'])

    def test_intentionally_removed_folder_is_not_recreated_until_reenabled(self):
        self.expire()
        (self.store.data / 'folder-removal-requested').touch()
        shutil.rmtree(self.store.root)
        with self.store.session() as s:
            s.tick()
            self.assertTrue(s.snapshot()['folder_removed'])
            self.assertEqual(s.snapshot()['files'], [])
            self.assertEqual(s.snapshot()['missing_recovery_count'], 0)
        self.assertFalse(self.store.root.exists())
        (self.store.data / 'folder-removal-requested').unlink()
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'], [])
        self.assertTrue(self.store.root.is_dir())

    def test_deleted_recovery_folder_is_unavailable_even_while_paused(self):
        deleted = self.expire()
        with self.store.session() as s:
            s.configure('paused', True)
        shutil.rmtree(self.store.root / '.transit-recovery')
        with self.store.session() as s:
            self.assertTrue(s.storage_recreated)
            self.assertEqual(s.snapshot()['files'][0]['status'], 'recovery_missing')
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                s.action(deleted['id'], 'restore')

    def test_status_detects_external_deletion_without_waiting_for_cleanup(self):
        deleted = self.expire()
        path = self.write('active.txt')
        self.tick()
        with self.store.session() as s:
            path.unlink()
            (self.store.root / '.transit-recovery' / deleted['id']).unlink()
            snapshot = s.snapshot()
            self.assertEqual(snapshot['missing_recovery_count'], 1)
            self.assertNotIn('active', [r['status'] for r in snapshot['files']])

    def test_removed_root_resets_history_without_erasing_system_trash(self):
        deleted = self.expire()
        trashed = self.home / 'trashed-folder'
        self.store.root.rename(trashed)
        vault_file = trashed / '.transit-recovery' / deleted['id']
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'], [])
            self.assertEqual(vault_file.read_bytes(), b'valuable data')

    def test_replaced_root_is_fresh_even_if_recreated_between_checks(self):
        self.expire()
        self.store.root.rename(self.home / 'old-folder')
        self.store.root.mkdir(mode=0o700)
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'], [])
            self.assertEqual(s.snapshot()['missing_recovery_count'], 0)

    def test_extension_uninstall_resets_once_and_keeps_active_files(self):
        extension = self.home / '.local/share/gnome-shell/extensions/transit@aaryabalan.local'
        extension.mkdir(parents=True)
        deleted = self.expire()
        active = self.write('keep.txt')
        self.tick()
        with self.store.session() as s:
            s.configure('lifetime_hours', 12)
        shutil.rmtree(extension)
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'], [])
            self.assertEqual(s.settings()['lifetime_hours'], 12)
        self.assertTrue(active.exists())
        self.assertFalse((self.store.root / '.transit-recovery' / deleted['id']).exists())
        extension.mkdir()
        rows = self.tick()
        self.assertEqual([r['name'] for r in rows], ['keep.txt'])
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['id'], rows[0]['id'])

    def test_disabling_or_upgrading_extension_does_not_reset_history(self):
        extension = self.home / '.local/share/gnome-shell/extensions/transit@aaryabalan.local'
        extension.mkdir(parents=True)
        metadata = extension / 'metadata.json'
        metadata.write_text('old version')
        deleted = self.expire()
        extension.rename(extension.with_name('old-version'))
        extension.mkdir()
        metadata.write_text('updated version')
        with self.store.session() as s:
            # Disable changes Shell state, not the installed directory.
            self.assertEqual(s.snapshot()['files'][0]['id'], deleted['id'])
            self.assertEqual(s.snapshot()['files'][0]['status'], 'deleted')

    def test_uninstall_with_missing_root_does_not_recreate_it(self):
        self.expire()
        shutil.rmtree(self.store.root)
        with self.store.session(uninstall=True) as s:
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM files').fetchone()[0], 0)
        self.assertFalse(self.store.root.exists())

    def test_replaced_or_symlinked_recovery_copy_cannot_be_restored(self):
        deleted = self.expire()
        original = self.store.root / '.transit-recovery' / deleted['id']
        original.rename(self.home / 'original-recovery')
        original.write_bytes(b'different file')
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'recovery_missing')
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                s.action(deleted['id'], 'restore')
        original.unlink()
        original.symlink_to(self.home / 'original-recovery')
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'recovery_missing')
        self.assertEqual((self.home / 'original-recovery').read_bytes(), b'valuable data')

    def test_purge_at_seven_days_and_keep_history(self):
        row = self.expire()
        self.now += RETENTION - 1
        self.assertEqual(self.tick()[0]['status'], 'deleted')
        self.now += 1
        self.assertEqual(self.tick()[0]['status'], 'purged')
        self.assertFalse((self.store.root / '.transit-recovery' / row['id']).exists())
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
        vault = self.store.root / '.transit-recovery'
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
        self.assertTrue((self.store.root / '.transit-recovery' / row['id']).exists())

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
            for path in (self.home, self.store.root, self.store.root / '.transit-recovery'):
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
                with patch('transit.core.os.unlink', side_effect=OSError('simulated interruption')):
                    s.tick()
        with self.store.session() as s:
            self.assertEqual(s.snapshot()['files'][0]['status'], 'deleted')
        self.assertFalse((self.store.root / 'note.txt').exists())

    def test_crash_after_link_recovers_restore(self):
        row = self.expire()
        with self.assertRaises(OSError):
            with self.store.session() as s:
                with patch('transit.core.os.unlink', side_effect=OSError('simulated interruption')):
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
                with patch('transit.core.os.link', side_effect=OSError('disk failure')):
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
