"""Exercise real GIO trash/delete dispatch against disposable directories."""
import importlib.util
import os
from unittest.mock import patch
from pathlib import Path
import tempfile
import subprocess
import unittest

try:
    spec = importlib.util.spec_from_file_location('transist_guard', Path(__file__).parents[1] / 'nautilus/transist_guard.py')
    guard_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard_module)
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    guard_module = None


@unittest.skipIf(guard_module is None, 'Requires GNOME Files Python/GI runtime')
class FolderGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.library = Path(cls.build.name) / 'guard.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(Path(__file__).parents[1] / 'nautilus/guard_native.c'), '-o', str(cls.library)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = self.home / '_transist'
        self.root.mkdir()
        self.guard = guard_module.FolderGuard(self.root, library=self.library)

    def tearDown(self):
        self.guard.close()
        self.temp.cleanup()

    def file(self, path):
        return Gio.File.new_for_path(str(path))

    def test_root_trash_and_delete_are_rejected_before_contents_change(self):
        child = self.root / 'valuable.txt'
        child.write_bytes(b'keep this')
        for operation in ('delete', 'trash'):
            with self.subTest(operation=operation), self.assertRaises(GLib.Error) as caught:
                getattr(self.file(self.root), operation)(None)
            self.assertTrue(caught.exception.matches(Gio.io_error_quark(), Gio.IOErrorEnum.PERMISSION_DENIED))
            self.assertEqual(caught.exception.message, guard_module.MESSAGE)
            self.assertEqual(child.read_bytes(), b'keep this')
            self.assertTrue(self.root.is_dir())
        self.assertEqual(self.guard.removal_attempts, 0)

    def test_children_and_other_folders_can_be_deleted(self):
        child = self.root / 'delete.txt'
        child.write_text('delete this')
        other = self.home / 'other-folder'
        other.mkdir()
        self.assertTrue(self.file(child).delete(None))
        self.assertTrue(self.file(other).delete(None))
        self.assertTrue(self.root.is_dir())
        self.assertEqual(self.guard.removal_attempts, 0)

    def test_only_exact_root_is_protected(self):
        nested = self.root / '_transist'
        nested.mkdir()
        similar = self.home / '_transist-backup'
        similar.mkdir()
        self.assertTrue(self.file(nested).delete(None))
        self.assertTrue(self.file(similar).delete(None))

    def test_disabling_allows_root_deletion_and_prepares_removal(self):
        self.guard.set_enabled(False)
        self.assertTrue(self.file(self.root).delete(None))
        self.assertFalse(self.root.exists())
        self.assertEqual(self.guard.removal_attempts, 1)

    def test_reenable_protects_again_without_restarting_file_manager(self):
        self.guard.set_enabled(False)
        self.assertTrue(self.file(self.root).delete(None))
        self.root.mkdir()
        self.guard.set_enabled(True)
        with self.assertRaises(GLib.Error):
            self.file(self.root).delete(None)
        self.assertTrue(self.root.exists())

    def test_nautilus_recursive_delete_stops_at_protected_root(self):
        child = self.root / 'child.txt'
        child.write_text('must survive')

        def delete_recursively(path):
            try:
                return self.file(path).delete(None)
            except GLib.Error as error:
                # This is Nautilus' recursion condition, verified in its source.
                if not error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_EMPTY):
                    raise
                for item in path.iterdir():
                    delete_recursively(item)
                return self.file(path).delete(None)

        with self.assertRaises(GLib.Error):
            delete_recursively(self.root)
        self.assertEqual(child.read_text(), 'must survive')
        self.guard.set_enabled(False)
        self.assertTrue(delete_recursively(self.root))
        self.assertFalse(self.root.exists())

    def test_disabled_removal_stops_service_and_records_request(self):
        self.guard.close()
        marker = self.home / 'folder-removal-requested'
        launcher = self.home / 'transist'
        launcher.touch()
        command = self.home / 'systemctl'
        command.write_text('#!/bin/sh\n[ "$*" = "--user stop transist.service" ]\n')
        command.chmod(0o700)
        self.guard = guard_module.FolderGuard(self.root, enabled=False,
                marker=marker, launcher=launcher, library=self.library)
        with patch.dict(os.environ, {'PATH': str(self.home)}):
            self.assertTrue(self.file(self.root).delete(None))
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)

    def test_service_stop_failure_preserves_root_and_contents(self):
        self.guard.close()
        marker = self.home / 'folder-removal-requested'
        launcher = self.home / 'transist'
        launcher.touch()
        command = self.home / 'systemctl'
        command.write_text('#!/bin/sh\nexit 1\n')
        command.chmod(0o700)
        child = self.root / 'keep.txt'
        child.write_text('keep')
        self.guard = guard_module.FolderGuard(self.root, enabled=False,
                marker=marker, launcher=launcher, library=self.library)
        with patch.dict(os.environ, {'PATH': str(self.home)}), self.assertRaises(GLib.Error):
            self.file(self.root).delete(None)
        self.assertEqual(child.read_text(), 'keep')
        self.assertFalse(marker.exists())

    def test_native_methods_are_restored_on_unload(self):
        self.guard.close()
        self.assertTrue(self.file(self.root).delete(None))
        self.root.mkdir()
        self.guard = guard_module.FolderGuard(self.root, library=self.library)
