// Generated with AI for personal use.
// Do NOT upload to extensions.gnome.org (EGO) unless you understand JavaScript
// and can maintain this code.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension, InjectionManager} from 'resource:///org/gnome/shell/extensions/extension.js';
import {screenshotPath} from './screenshot-path.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

export default class Transist extends Extension {
    enable() {
        this._resumeAfterFolderRemoval();
        this._settings = this.getSettings('org.gnome.shell.extensions.transist');
        this._injections = new InjectionManager();
        const pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) || GLib.get_home_dir();
        const folderName = GLib.dgettext('gnome-shell', 'Screenshots');
        const destination = GLib.build_filenamev([GLib.get_home_dir(), '_transist']);
        const settings = this._settings;
        // GNOME's own writer still handles PNG data, collisions, clipboard,
        // lockdown policy, notifications and recent files. Only redirect its
        // exact screenshot-directory lookup; never change XDG Pictures.
        this._injections.overrideMethod(GLib, 'build_filenamev', original => function (parts) {
            if (settings.get_boolean('direct-screenshots')) {
                const redirected = screenshotPath(parts, pictures, folderName, destination);
                if (redirected !== null)
                    return redirected;
            }
            return original.call(this, parts);
        });
        this._settings.set_boolean('direct-screenshots-ready', true);
        this._indicator = new PanelMenu.Button(0.0, 'Transist');
        this._indicator.add_child(new St.Icon({
            icon_name: 'document-open-recent-symbolic',
            style_class: 'system-status-icon',
        }));
        const title = new PopupMenu.PopupMenuItem('Transist · files for now', {reactive: false});
        this._indicator.menu.addMenuItem(title);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._indicator.menu.addAction('Files, History & Settings', () => this.openPreferences());
        this._indicator.menu.addAction('Open _transist folder', () => this._openFolder());
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    _openFolder() {
        const uri = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_home_dir(), '_transist'])).get_uri();
        Gio.AppInfo.launch_default_for_uri_async(uri, null, null, (_source, result) => {
            try {
                Gio.AppInfo.launch_default_for_uri_finish(result);
            } catch (error) {
                if (this._indicator)
                    Main.notify('Transist', error.message);
            }
        });
    }

    _resumeAfterFolderRemoval() {
        const marker = Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_data_dir(), 'transist', 'folder-removal-requested']));
        if (!marker.query_exists(null))
            return;
        try {
            marker.delete(null);
            const process = Gio.Subprocess.new(['systemctl', '--user', 'start', 'transist.service'], Gio.SubprocessFlags.NONE);
            process.wait_check_async(null, (source, result) => {
                try {
                    source.wait_check_finish(result);
                } catch (error) {
                    Main.notify('Transist', `Could not restart cleanup: ${error.message}`);
                }
            });
        } catch (error) {
            Main.notify('Transist', error.message);
        }
    }

    disable() {
        this._settings?.set_boolean('direct-screenshots-ready', false);
        this._injections?.clear();
        this._injections = null;
        this._settings = null;
        this._indicator?.destroy();
        this._indicator = null;
    }
}
