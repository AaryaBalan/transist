"""GNOME Files companion: reject deletion of ~/_transit, not its contents.

Nautilus has no public deletion-veto provider. This companion wraps the native
GFile interface used inside Nautilus. Offsets come from the installed typelib,
not a hard-coded GLib layout. The hook affects this process only; it is not a
filesystem lock and does not protect against terminal commands or other apps.
"""
import ctypes
import logging
import os
from pathlib import Path
import subprocess

import gi
gi.require_version('Gio', '2.0')
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('Nautilus', '4.1')
from gi.repository import Adw, Gio, GLib, GObject, Gtk, Nautilus

UUID = 'transit@aaryabalan.local'
MESSAGE = 'Deleting _transit is restricted. Disable the Transit extension first.'
_guard = None  # Retain native callbacks for the lifetime of the Nautilus process.


def extension_active():
    reply = Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
        'org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions',
        'org.gnome.Shell.Extensions', 'GetExtensionInfo',
        GLib.Variant('(s)', (UUID,)), GLib.VariantType.new('(a{sv})'),
        Gio.DBusCallFlags.NONE, 2000, None)
    return reply.unpack()[0].get('state') == 1


class FolderGuard:
    """Wrap GFile delete/trash without changing ownership or permissions."""
    def __init__(self, root, enabled=True, marker=None, launcher=None, library=None):
        self.root = Gio.File.new_for_path(os.fspath(root))
        self._native = ctypes.CDLL(os.fspath(library or Path(__file__).with_name('transit_guard_native.so')))
        gio = ctypes.CDLL('libgio-2.0.so.0')
        self._gobject = ctypes.CDLL('libgobject-2.0.so.0')
        glib = ctypes.CDLL('libglib-2.0.so.0')
        self._gobject.g_type_class_ref.argtypes = [ctypes.c_size_t]
        self._gobject.g_type_class_ref.restype = ctypes.c_void_p
        self._gobject.g_type_class_unref.argtypes = [ctypes.c_void_p]
        self._gobject.g_type_class_unref.restype = None
        self._gobject.g_type_interface_peek.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self._gobject.g_type_interface_peek.restype = ctypes.c_void_p
        gio.g_io_error_quark.restype = ctypes.c_uint
        capsule_pointer = ctypes.pythonapi.PyCapsule_GetPointer
        capsule_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
        capsule_pointer.restype = ctypes.c_void_p
        self._class = self._gobject.g_type_class_ref(hash(self.root.__gtype__))
        interface = self._gobject.g_type_interface_peek(self._class, hash(Gio.File.__gtype__))
        if not interface:
            raise RuntimeError('The local file implementation has no GFile interface')
        info = Gio.File.__info__.get_iface_struct()
        fields = {field.get_name(): field.get_offset() for field in info.get_fields()}
        slots = []
        for name in ('delete_file', 'trash'):
            offset = fields.get(name, -1)
            if offset < 0 or offset + ctypes.sizeof(ctypes.c_void_p) > info.get_size():
                raise RuntimeError(f'Unsupported GFile interface: {name}')
            slot = ctypes.c_void_p.from_address(interface + offset)
            if not slot.value:
                raise RuntimeError(f'Missing GFile implementation: {name}')
            slots.append(ctypes.addressof(slot))
        self._native.transit_install.argtypes = [ctypes.c_void_p] * 5 + [ctypes.c_uint, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
        self._native.transit_install.restype = ctypes.c_int
        self._native.transit_set_enabled.argtypes = [ctypes.c_int]
        self._native.transit_set_enabled.restype = None
        self._native.transit_uninstall.restype = None
        self._native.transit_removal_attempts.restype = ctypes.c_uint
        self.set_enabled(enabled)
        if not self._native.transit_install(capsule_pointer(self.root.__gpointer__, None), *slots,
                gio.g_file_equal, glib.g_set_error_literal, gio.g_io_error_quark(),
                int(Gio.IOErrorEnum.PERMISSION_DENIED), os.fsencode(marker) if marker else None,
                os.fsencode(launcher) if launcher else None):
            raise RuntimeError('Could not install the Transit file-operation guard')

    def set_enabled(self, enabled):
        self._native.transit_set_enabled(-1 if enabled is None else int(enabled))

    @property
    def removal_attempts(self):
        return self._native.transit_removal_attempts()

    def close(self):
        self._native.transit_uninstall()
        self._gobject.g_type_class_unref(self._class)


def restyle_restriction_dialog(dialog):
    """Change only a native error dialog carrying our exact error message."""
    if not isinstance(dialog, Adw.AlertDialog):
        return
    details = dialog.get_extra_child()
    if not isinstance(details, Gtk.Label) or details.get_text() != MESSAGE:
        return
    dialog.set_heading('Deleting _transit is restricted')
    dialog.set_body('Disable the Transit extension first. You can still delete individual files inside _transit.')
    dialog.set_extra_child(None)
    for response in ('delete', 'delete_all', 'skip', 'skip_all', 'skip_files', 'retry'):
        if dialog.has_response(response):
            dialog.remove_response(response)
    dialog.set_response_label('cancel', 'Close')
    dialog.set_default_response('cancel')
    dialog.set_close_response('cancel')


class TransitFolderProtection(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        super().__init__()
        global _guard
        if _guard is None:
            _guard = FolderGuard(Path.home() / '_transit', enabled=None,
                                 marker=self._marker(), launcher=Path.home() / '.local/bin/transit')
        self._watched = set()
        self._windows = Gtk.Window.get_toplevels()
        self._windows.connect('items-changed', self._watch_windows)
        self._watch_windows()
        Gio.bus_get_sync(Gio.BusType.SESSION, None).signal_subscribe(
            None, 'org.gnome.Shell.Extensions', 'ExtensionStateChanged', None, UUID,
            Gio.DBusSignalFlags.NONE, self._extension_changed)
        self._refresh_state()
        # Detect a Shell/service restart too; worker threads never call Python.
        Gio.bus_get_sync(Gio.BusType.SESSION, None).signal_subscribe(
            'org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
            '/org/freedesktop/DBus', 'org.gnome.Shell.Extensions',
            Gio.DBusSignalFlags.NONE, self._owner_changed)

    @staticmethod
    def _marker():
        return Path(GLib.get_user_data_dir()) / 'transit' / 'folder-removal-requested'

    def _refresh_state(self):
        try:
            _guard.set_enabled(extension_active())
        except GLib.Error:
            _guard.set_enabled(None)
            logging.exception('Transit could not query extension state')
        return GLib.SOURCE_REMOVE

    def _owner_changed(self, _bus, _sender, _path, _interface, _signal, parameters):
        _name, _old, new = parameters.unpack()
        _guard.set_enabled(None)
        if new:
            GLib.idle_add(self._refresh_state)

    def _extension_changed(self, _bus, _sender, _path, _interface, _signal, parameters):
        uuid, state = parameters.unpack()
        if uuid != UUID:
            return
        active = state.get('state') == 1
        _guard.set_enabled(active)
        if active and self._marker().exists():
            self._marker().unlink()
            subprocess.Popen(['systemctl', '--user', 'start', 'transit.service'])

    def _watch_windows(self, *_args):
        for i in range(self._windows.get_n_items()):
            window = self._windows.get_item(i)
            if window in self._watched:
                continue
            self._watched.add(window)
            window.connect('destroy', lambda win: self._watched.discard(win))
            if hasattr(window, 'get_dialogs'):
                dialogs = window.get_dialogs()
                dialogs.connect('items-changed', self._dialogs_changed)
                self._dialogs_changed(dialogs, 0, 0, dialogs.get_n_items())
            else:
                # D-Bus operations can present an unparented AdwDialog host.
                GLib.idle_add(self._scan_dialogs, window)

    @staticmethod
    def _scan_dialogs(widget):
        if isinstance(widget, Adw.AlertDialog):
            restyle_restriction_dialog(widget)
        else:
            child = widget.get_first_child()
            while child:
                TransitFolderProtection._scan_dialogs(child)
                child = child.get_next_sibling()
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _dialogs_changed(dialogs, position, _removed, added):
        for i in range(position, position + added):
            restyle_restriction_dialog(dialogs.get_item(i))

    def get_file_items(self, _files):
        return []
