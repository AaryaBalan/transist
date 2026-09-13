// Generated with AI for personal use.
// Do NOT upload to extensions.gnome.org (EGO) unless you understand JavaScript
// and can maintain this code.
import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import { fileRows, lifetimeOptions, lifetimeLabel } from './view-model.js';

export default class TransistPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        this._window = window;
        this._closed = false;
        this._busy = false;
        this._sync = false;
        this._queue = [];
        this._views = {};
        this._snapshot = null;
        this._backend = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'transist']);
        window.set_default_size(820, 720);
        window.set_search_enabled(true);
        for (const [name, title, icon] of [['active', 'Active Files', 'folder-symbolic'], ['history', 'Recently Deleted', 'document-open-recent-symbolic']]) {
            const page = new Adw.PreferencesPage({ name, title, icon_name: icon });
            const overview = new Adw.PreferencesGroup();
            const status = new Adw.ActionRow({ title: 'Connecting to cleanup service…', use_markup: false });
            status.add_suffix(this._button('Open Folder', () => this._openFolder()));
            status.add_suffix(this._button('Refresh', () => this._refresh()));
            overview.add(status);
            page.add(overview);
            const searchGroup = new Adw.PreferencesGroup();
            const search = new Gtk.SearchEntry({ placeholder_text: 'Search filenames', hexpand: true });
            searchGroup.add(search);
            page.add(searchGroup);
            const files = new Adw.PreferencesGroup({ title: name === 'active' ? 'Your temporary collection' : 'Recovery history', description: name === 'active' ? 'Each temporary file has its own cleanup timer. Use the eye icon to open a file.' : 'Files removed by automatic cleanup can be restored within seven days.' });
            page.add(files);
            window.add(page);
            this._views[name] = { status, search, files, children: [], limit: 100 };
            search.connect('search-changed', () => {
                this._views[name].limit = 100;
                this._renderFiles(name);
            });
        }
        const settings = new Adw.PreferencesPage({ name: 'settings', title: 'Settings', icon_name: 'emblem-system-symbolic' });
        const guide = new Adw.PreferencesGroup({ title: 'How Transist works', description: 'A temporary home for files you only need for a while.' });
        for (const [title, subtitle] of [
            ['1. Add files', 'Place files directly in ~/_transist, or enable screenshot capture below. Each file’s timer starts when Transist first detects it.'],
            ['2. Choose a cleanup window', 'Temporary files leave _transist when their timers run out. Keep Permanently exempts a file from automatic cleanup.'],
            ['3. Recover within seven days', 'Expired files move to Recently Deleted. Recovery copies still use disk space and are permanently deleted seven days later. Restore starts a fresh timer using your selected window.'],
        ])
            guide.add(new Adw.ActionRow({ title, subtitle, use_markup: false }));
        settings.add(guide);
        const appearance = new Adw.PreferencesGroup({ title: 'Appearance' });
        appearance.add(new Adw.ActionRow({ title: 'Follow GNOME', subtitle: 'Native preferences styling and the system light/dark preference. No custom color theme.', use_markup: false }));
        settings.add(appearance);
        this._controls = new Adw.PreferencesGroup({ title: 'Screenshot capture & cleanup', sensitive: false });
        this._lifetime = new Adw.ComboRow({
            title: 'Automatically remove files after',
            subtitle: 'Applies to new and existing temporary files, measured from each timer’s start. A shorter window can make files due for cleanup immediately.',
            model: Gtk.StringList.new(lifetimeOptions.map(lifetimeLabel)),
            selected: 1,
            use_markup: false,
        });
        this._lifetime.connect('notify::selected', () => {
            if (!this._sync && lifetimeOptions[this._lifetime.selected] !== undefined)
                this._refresh(['config', 'lifetime_hours', String(lifetimeOptions[this._lifetime.selected])]);
        });
        this._controls.add(this._lifetime);
        const captureRow = new Adw.ActionRow({ title: 'Store screenshots in _transist', subtitle: 'Move new images from the source folder after 30 seconds.', use_markup: false });
        this._capture = this._switch(captureRow, 'capture_screenshots');
        this._controls.add(captureRow);
        this._folder = new Adw.EntryRow({ title: 'Screenshot source folder', show_apply_button: true });
        this._folder.connect('apply', () => this._refresh(['config', 'screenshot_folder', this._folder.text]));
        this._controls.add(this._folder);
        const pauseRow = new Adw.ActionRow({ title: 'Pause automatic cleanup', subtitle: 'Stops screenshot moves, expiry, and purging. Timers keep advancing while paused.', use_markup: false });
        this._pause = this._switch(pauseRow, 'paused');
        this._controls.add(pauseRow);
        settings.add(this._controls);
        const info = new Adw.PreferencesGroup({ title: 'Storage & service' });
        this._service = new Adw.ActionRow({ title: 'Background cleanup', subtitle: 'Checking service…', use_markup: false });
        this._service.add_suffix(this._button('Refresh', () => this._refresh()));
        info.add(this._service);
        for (const [title, subtitle] of [
            ['Temporary folder', '~/_transist — regular files directly inside this folder only.'],
            ['Cleanup timing', 'Checks every 10 seconds while the service is running. Files must be unchanged for 30 seconds before removal. Making a file temporary starts a fresh timer using your selected window.'],
            ['Independent service', 'Closing preferences or disabling the top-bar extension does not stop cleanup. Use Pause above, or stop transist.service.'],
        ])
            info.add(new Adw.ActionRow({ title, subtitle, use_markup: false }));
        settings.add(info);
        window.add(settings);
        window.connect('close-request', () => {
            this._closed = true;
            if (this._timer) {
                GLib.Source.remove(this._timer);
                this._timer = 0;
            }
            this._queue.length = 0;
            // Let any already-started file operation finish safely without UI updates.
            return false;
        });
        this._refresh();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _button(label, callback) {
        const button = new Gtk.Button({ label, valign: Gtk.Align.CENTER });
        button.connect('clicked', callback);
        return button;
    }

    _switch(row, key) {
        const control = new Gtk.Switch({ valign: Gtk.Align.CENTER });
        row.add_suffix(control);
        row.set_activatable_widget(control);
        control.connect('notify::active', () => {
            if (!this._sync)
                this._refresh(['config', key, String(control.active)]);
        });
        return control;
    }

    _openFolder() {
        this._openPath(this._snapshot?.folder ?? GLib.build_filenamev([GLib.get_home_dir(), '_transist']));
    }

    _openFile(name) {
        this._openPath(GLib.build_filenamev([this._snapshot.folder, name]));
    }

    _openPath(path) {
        const uri = Gio.File.new_for_path(path).get_uri();
        Gio.AppInfo.launch_default_for_uri_async(uri, null, null, (_source, result) => {
            try {
                Gio.AppInfo.launch_default_for_uri_finish(result);
            } catch (error) {
                if (!this._closed)
                    this._window.add_toast(new Adw.Toast({ title: error.message }));
            }
        });
    }

    _command(args) {
        return new Promise((resolve, reject) => {
            let process;
            try {
                process = Gio.Subprocess.new([this._backend, ...args], Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
            } catch (error) {
                reject(new Error(`Install or update the Transist background service using install.py. ${error.message}`));
                return;
            }
            process.communicate_utf8_async(null, null, (source, result) => {
                try {
                    const [, output, stderr] = source.communicate_utf8_finish(result);
                    if (!source.get_successful())
                        throw new Error(stderr.trim() || 'Background command failed.');
                    resolve(JSON.parse(output));
                } catch (error) {
                    reject(error);
                }
            });
        });
    }

    async _refresh(operation = null) {
        if (this._closed)
            return;
        if (this._busy) {
            if (operation)
                this._queue.push(operation);
            return;
        }
        this._busy = true;
        if (operation)
            this._setSensitive(false);
        try {
            const snapshot = await this._command(operation || ['status']);
            if (this._closed)
                return;
            const first = !this._snapshot;
            this._snapshot = snapshot;
            this._syncControls();
            if (first || operation?.[1] === 'screenshot_folder')
                this._folder.text = snapshot.settings.screenshot_folder;
            const service = snapshot.service === 'active' ? (snapshot.settings.paused ? 'Paused' : 'Cleanup running') : 'Service offline — run: systemctl --user start transist.service';
            this._service.subtitle = service;
            for (const [name, view] of Object.entries(this._views)) {
                view.status.title = service;
                this._renderFiles(name);
            }
        } catch (error) {
            if (!this._closed) {
                for (const view of Object.values(this._views))
                    view.status.title = error.message;
                this._service.subtitle = error.message;
                this._syncControls();
                if (operation)
                    this._window.add_toast(new Adw.Toast({ title: error.message }));
            }
        } finally {
            this._busy = false;
            if (!this._closed) {
                this._setSensitive(Boolean(this._snapshot));
                if (this._queue.length)
                    this._refresh(this._queue.shift());
            }
        }
    }

    _syncControls() {
        if (!this._snapshot)
            return;
        this._sync = true;
        this._capture.active = this._snapshot.settings.capture_screenshots;
        this._pause.active = this._snapshot.settings.paused;
        this._lifetime.selected = lifetimeOptions.indexOf(this._snapshot.settings.lifetime_hours ?? 5);
        const duration = lifetimeLabel(this._snapshot.settings.lifetime_hours);
        this._views.active.files.description = `Temporary files are removed after ${duration}; permanent files stay. Change the window in Settings. Use the eye icon to open a file.`;
        this._views.history.files.description = `Recover within seven days of removal. Restoring starts a fresh ${duration} timer.`;
        this._sync = false;
    }

    _setSensitive(value) {
        this._controls.sensitive = value;
        for (const view of Object.values(this._views))
            view.files.sensitive = value;
    }

    _renderFiles(name) {
        if (!this._snapshot)
            return;
        const view = this._views[name];
        for (const child of view.children)
            view.files.remove(child);
        view.children = [];
        const add = child => {
            view.files.add(child);
            view.children.push(child);
        };
        const rows = fileRows(this._snapshot, name, view.search.text);
        view.status.subtitle = `${rows.length} ${name === 'active' ? 'active files' : 'history entries'}${view.search.text ? ' matching your search' : ''}`;
        if (!rows.length)
            add(new Adw.ActionRow({ title: view.search.text ? 'No matching files' : name === 'active' ? 'Your folder is clear' : 'No deleted files yet', subtitle: name === 'active' ? 'Place files directly in ~/_transist to start their timers.' : 'Expired files appear here for recovery.', use_markup: false }));
        for (const item of rows.slice(0, view.limit)) {
            const row = new Adw.ActionRow({ title: item.name, subtitle: item.subtitle, use_markup: false, title_lines: 1, subtitle_lines: 2 });
            row.set_tooltip_text(item.name);
            row.add_prefix(new Gtk.Image({ icon_name: item.icon }));
            if (name === 'active') {
                const viewFile = new Gtk.Button({ icon_name: 'view-reveal-symbolic', valign: Gtk.Align.CENTER, tooltip_text: `Open ${item.name}` });
                viewFile.update_property([Gtk.AccessibleProperty.LABEL], [`Open ${item.name}`]);
                viewFile.connect('clicked', () => this._openFile(item.name));
                row.add_suffix(viewFile);
            }
            const action = this._button(item.label, () => this._refresh(['action', item.action, item.id]));
            action.sensitive = item.enabled;
            row.add_suffix(action);
            add(row);
        }
        if (rows.length > view.limit)
            add(this._button(`Show more (${rows.length - view.limit} remaining)`, () => {
                view.limit += 100;
                this._renderFiles(name);
            }));
    }
}
