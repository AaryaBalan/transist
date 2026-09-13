"""Opt-in native UI smoke test; only disposable folders are deleted.
Run from the repository: dbus-run-session -- python3 tests/nautilus_smoke.py
Requires an active graphical session and the Files/Python extension runtime.
"""
import os
from pathlib import Path
import tempfile
import subprocess
import threading
import time

base = Path(tempfile.mkdtemp(prefix='transist-nautilus-'))
os.environ.update(HOME=str(base), XDG_DATA_HOME=str(base/'data'), XDG_CONFIG_HOME=str(base/'config'), XDG_CACHE_HOME=str(base/'cache'), GSETTINGS_BACKEND='memory', NO_AT_BRIDGE='1', NAUTILUS_PYTHON_DEBUG='all')
root = base/'_transist'
root.mkdir()
(root/'sample.txt').write_text('sample must survive blocked root deletion')
plugin = base/'data/nautilus-python/extensions/transist_guard.py'
plugin.parent.mkdir(parents=True)
repo = Path(__file__).resolve().parents[1]
source = (repo/'nautilus/transist_guard.py').read_text()
source = source.replace("dialog.set_close_response('cancel')", "dialog.set_close_response('cancel')\n    GLib.timeout_add(350, _capture_and_close, dialog)")
source = source.replace('restyle_restriction_dialog(dialogs.get_item(i))', """dialog = dialogs.get_item(i)
            restyle_restriction_dialog(dialog)
            if isinstance(dialog, Adw.AlertDialog) and dialog.has_response('delete') and '_transist' in dialog.get_heading():
                dialog.set_close_response('delete')
                GLib.timeout_add(250, lambda d=dialog: (d.close(), GLib.SOURCE_REMOVE)[1])""")
source = source.replace("restyle_restriction_dialog(widget)", "restyle_restriction_dialog(widget)\n            if widget.has_response('delete') and '_transist' in widget.get_heading():\n                widget.set_close_response('delete')\n                GLib.timeout_add(250, lambda d=widget: (d.close(), GLib.SOURCE_REMOVE)[1])")
source += '''
def _capture_and_close(dialog):
    from gi.repository import Gsk
    window = dialog.get_root()
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    renderer = Gsk.Renderer.new_for_surface(window.get_surface())
    renderer.render_texture(snapshot.to_node(), None).save_to_png(str(Path.home()/'restricted-dialog.png'))
    renderer.unrealize()
    with (Path.home()/'blocked-dialogs').open('a') as stream:
        stream.write(dialog.get_heading() + '\\n')
    dialog.close()
    return GLib.SOURCE_REMOVE
'''
plugin.write_text(source)
subprocess.run(['cc', '-shared', '-fPIC', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', str(repo/'nautilus/guard_native.c'), '-o', str(plugin.with_name('transist_guard_native.so'))], check=True)
import gi
from gi.repository import Gio, GLib
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
names = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames', None, GLib.VariantType.new('(as)'), Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
assert not {'org.gnome.Shell', 'org.gnome.Shell.Extensions', 'org.gnome.Nautilus'}.intersection(names), 'Refusing a desktop bus: run under dbus-run-session'
state = {'enabled': True}
xml = '<node><interface name="org.gnome.Shell.Extensions"><method name="GetExtensionInfo"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method></interface></node>'
def method_call(_conn, _sender, _path, _iface, _method, _args, invocation):
    print('Guard queried extension state', state['enabled'], flush=True)
    invocation.return_value(GLib.Variant('(a{sv})', ({'state': GLib.Variant('i', 1 if state['enabled'] else 2)},)))
bus.register_object('/org/gnome/Shell/Extensions', Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], method_call, None, None)
Gio.bus_own_name_on_connection(bus, 'org.gnome.Shell.Extensions', Gio.BusNameOwnerFlags.NONE, None, None)
loop = GLib.MainLoop()
result = {'error': None}
log = (base/'nautilus.log').open('w')
process = subprocess.Popen(['nautilus', '--new-window', str(base)], stdout=log, stderr=log)
def run():
    try:
        time.sleep(3)
        reply = bus.call_sync('org.gnome.Nautilus', '/org/gnome/Nautilus/FileOperations2', 'org.freedesktop.DBus.Introspectable', 'Introspect', None, GLib.VariantType.new('(s)'), Gio.DBusCallFlags.NONE, 5000, None)
        def request(method, paths):
            bus.call_sync('org.gnome.Nautilus', '/org/gnome/Nautilus/FileOperations2', 'org.gnome.Nautilus.FileOperations2', method, GLib.Variant('(asa{sv})', ([p.as_uri() for p in paths], {})), None, Gio.DBusCallFlags.NONE, 5000, None)
        def wait_for(predicate):
            for _ in range(300):
                if predicate():
                    return
                time.sleep(0.1)
            raise AssertionError('Timed out waiting for native Files operation')
        blocked = base/'blocked-dialogs'
        request('TrashURIs', [root])
        wait_for(lambda: blocked.exists() and len(blocked.read_text().splitlines()) >= 1)
        assert (root/'sample.txt').read_text() == 'sample must survive blocked root deletion'
        print('Native Trash: blocked; folder and contents preserved', flush=True)
        request('DeleteURIs', [root])
        wait_for(lambda: len(blocked.read_text().splitlines()) >= 2)
        assert (root/'sample.txt').is_file()
        print('Native permanent Delete: blocked; contents preserved', flush=True)
        child = root/'child-to-trash.txt'
        child.write_text('disposable')
        other = base/'other-folder'
        other.mkdir()
        request('TrashURIs', [child, other])
        wait_for(lambda: not child.exists() and not other.exists())
        assert root.is_dir()
        print('Child file and unrelated folder: normal Trash allowed', flush=True)
        state['enabled'] = False
        bus.emit_signal(None, '/org/gnome/Shell/Extensions', 'org.gnome.Shell.Extensions', 'ExtensionStateChanged', GLib.Variant('(sa{sv})', ('transist@aaryabalan.local', {'state': GLib.Variant('i', 2)})))
        time.sleep(0.2)
        request('TrashURIs', [root])
        wait_for(lambda: not root.exists())
        print('Extension disabled: root Trash allowed', flush=True)
        print('Fixture:', base, flush=True)
    except Exception as error:
        result['error'] = str(error)
        print('ERROR:', error, flush=True)
    finally:
        process.terminate()
        process.wait(timeout=5)
        log.close()
        print('Nautilus log:', base/'nautilus.log', flush=True)
        GLib.idle_add(loop.quit)
threading.Thread(target=run, daemon=True).start()
loop.run()
if result['error']:
    raise SystemExit(1)
