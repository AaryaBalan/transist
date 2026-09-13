# Transist — GNOME Extension

**Files, recovery history, and settings in one native preferences window.**

Drop any regular file directly into `~/_transist`. Choose a cleanup window of
**1, 5, 12, 24, 48, or 72 hours, or 1 week** in Settings (default: five hours).
Expired files remain recoverable for seven days. Restore starts a fresh timer
using your selected window; permanent files do not expire.

## Native preferences update

There is **no separate Transist desktop app**. Open GNOME Extensions → Transist →
Settings, or choose **Files, History & Settings** from the top-bar menu.

The preferences window contains:

- **Active Files:** search filenames, view countdowns, open individual files with the eye icon, keep permanently, or make temporary.
- **Recently Deleted:** search history and restore eligible files.
- **Settings:** how cleanup works, cleanup window, screenshot capture, screenshot folder, pause, and service status.
- **Credits:** Aarya B, [GitHub profile](https://github.com/AaryaBalan),
  [source repository](https://github.com/AaryaBalan/transist), and a link to star the repo.

The interface uses GTK 4 / libadwaita directly inside `prefs.js`, following GNOME's
native system light/dark appearance. It does not force a custom palette or inject
Shell CSS into preferences. A custom Shell-only theme does not necessarily theme
GTK/libadwaita windows. The previous app's saved theme value is ignored.

A small **headless Python cleanup service** is still installed. It has no window
or application-menu entry and keeps cleanup working while preferences are closed.
There is no Python GTK / PyGObject dependency anymore.

## Install or upgrade

Requires **GNOME Shell 45–50** (target versions, still needing live compatibility
checks), its GTK 4/libadwaita/GJS extension-preferences runtime, Python **3.10+**, and
a systemd user session for automatic startup.

1. Close the old Transist app and any open Transist preferences window.
2. Extract this updated ZIP into a **new folder**; do not merge it into the old source tree.
3. Open a terminal in the extracted `transist` directory and run, **without sudo**:

```bash
python3 install.py
```

4. Log out and back in to reload GNOME's cached extension code, then run:

```bash
gnome-extensions enable transist@aaryabalan.local
gnome-extensions prefs transist@aaryabalan.local
```

The updater removes the old Transist application-menu entry, app icon, and obsolete
GUI source files. It preserves your files, permanent flags, timers, recovery copies,
and history database. Cleanup starts immediately; existing deadlines still apply.
New installations default screenshot capture to off. Existing capture settings
are preserved.

The program directory retains the internal name `transist-app` for upgrade
compatibility, but now contains only the headless backend. The old
`~/.local/bin/transist gui` command is a compatibility alias that opens GNOME
extension preferences instead of launching an app.

This GUI now targets GNOME only. Other desktops can still use the CLI/service with
`python3 install.py --no-extension`, but there is no standalone graphical app.
Without systemd, use `--no-service` and supervise `~/.local/bin/transist daemon`
yourself; no alternate autostart integration is installed.

## Use it

1. Open **Transist extension preferences**.
2. Click **Open Folder** and place files directly into `~/_transist`.
3. In **Settings**, choose **Automatically remove files after**. This saves immediately
   and applies to new and existing temporary files from each timer's original start.
   Shortening the window can make older files expire on the next cleanup cycle.
4. In **Active Files**, click a file's **eye icon** to open it in its default app,
   or select **Keep Permanently** or **Make Temporary**.
5. In **Recently Deleted**, select **Restore** during the recovery window. Its label
   shows the duration of the fresh timer.
6. In **Settings**, enable **Store screenshots directly in _transist** for GNOME's
   built-in screenshot tool. After upgrading, log out/in once to load the new Shell hook.
   For other screenshot apps, use **Import screenshots from another folder** or
   configure that app to save into `_transist` itself.
7. Use each page's filename search; lists load 100 entries at a time with **Show more**.

Missing backend and operation failures appear in preferences, rather than silently
opening another app. The UI refreshes every ten seconds and performs backend calls
asynchronously. Closing preferences stops its polling; already-started file
operations may finish safely in the background.

### Screenshot behavior

**Direct saving:** turn on **Store screenshots directly in _transist**. GNOME's
built-in screenshot tool writes new screenshots directly into `~/_transist`, with
no import delay or extra copy in Pictures. GNOME handles filename collisions,
clipboard contents, and notifications with the actual saved path. Existing images
stay where they are. Turning it off or disabling the extension restores GNOME's
normal save location. Direct saving continues while automatic cleanup is paused.
This option defaults to off and does not change other apps' save settings or screen
recording destinations. Preferences shows a logout/login message until the updated
Shell hook has loaded. The service discovers directly saved files on its next
10-second cycle, so the Active Files list may take a moment to show them.

**Folder import for other apps:** enable **Import screenshots from another folder**
and set its source directory. New PNG, JPEG, WebP, AVIF, BMP, and TIFF files are moved
after 30 seconds without changes. Existing images are left alone. Turning import
off and on establishes a new baseline. Use a dedicated screenshot folder, since
every new image there is eligible. Notifications from those apps may still point
to the old path after importing.

Other screenshot programs can also be configured to save directly into `~/_transist`; those files receive timers without the capture setting. Screen recordings and documents placed directly into `_transist` work like all other regular files. The capture setting does not watch the Videos folder.

### Exact lifetime rules

| Event | Result |
| --- | --- |
| File first detected directly in `_transist` | Timer starts using the selected cleanup window |
| Selected deadline reached | Moves to hidden private recovery storage on the next cleanup cycle |
| Change cleanup window | Existing temporary deadlines are recalculated from their timer starts; permanent files and recovery deadlines are unchanged |
| Restore within seven days of that move | Returns to `_transist` with a fresh timer using the current window |
| Same name already exists on restore | Restored file gets a unique suffix; existing item remains untouched |
| Keep permanently | File stays in place with no expiry |
| Make temporary | New timer starts using the current window |
| Seven days after the move to recovery | Recovery copy is permanently unlinked on the next cycle; filename/timestamps remain in history |
| Pause | No automatic screenshot moves, expiry, or purging; clocks still advance |
| Resume | Overdue files are processed; pause does not extend recovery eligibility |
| Reboot / suspend / logout | Persisted deadlines survive; overdue work resumes when the service runs again |

The service polls every **10 seconds**. Timing starts from first observation, not the file's old creation/modification timestamp. An unobserved file placed while the service is stopped receives its timer when the service next discovers it. Recently changing files wait until unchanged for **30 seconds** before expiry. A powered-off computer cannot clean files; a normal user service is not guaranteed to run after the last login session ends.

### Scope and file handling

- Processes **regular files directly inside** `_transist`, including hidden regular files and every extension/type.
- Leaves subdirectories, symbolic links, sockets, and other special files alone. Files with multiple hard links are tracked but not automatically expired.
- Renaming a file within `_transist` is treated as removing one item and adding a new one: it starts a new timer and does not inherit the old permanent flag. Replacing it with a different inode also creates a new item.
- Recovery is `~/_transist/.transist-recovery` (private, mode 0700). **Recovery files still consume disk space.** This is reversible deletion from the visible folder, not immediate disk-space reclamation.
- History/settings are in `${XDG_DATA_HOME:-~/.local/share}/transist/state.sqlite3`. Keep this database together with the recovery directory in backups. Do not delete or hand-edit either while cleanup is running.
- Expiry and restore use same-filesystem, no-overwrite hard links plus unlink, with a persisted intent record. An interrupted move is reconciled on the next operation.
- Screenshot imports copy to private staging, flush the copy, publish without overwriting, and only remove the original if its observed identity/content metadata still match. Interrupted imports can leave a staging copy; these `capture-*` files are intentionally retained, not automatically purged.
- SQLite or filesystem failures are logged, and the daemon retries on its next cycle. Check service logs if cleanup stops progressing. A failing file can delay later operations in that cycle.
- The quiet-period check is not a lock against a program resuming writes later. Pause cleanup while using this folder for long-running recordings or ongoing work. Permanent files remain ordinary editable files.
- Disabling the GNOME extension removes the top-bar UI and restores GNOME's normal screenshot destination. Background cleanup and folder imports keep running. To stop cleanup, use Settings → Pause, or stop the service.

## Service and command line

```bash
systemctl --user status transist.service
journalctl --user -u transist.service -n 50
systemctl --user stop transist.service
systemctl --user start transist.service

~/.local/bin/transist status
~/.local/bin/transist config paused true
~/.local/bin/transist config paused false
~/.local/bin/transist config lifetime_hours 24
~/.local/bin/transist config capture_screenshots true
~/.local/bin/transist config screenshot_folder "$HOME/Pictures/Screenshots"
```

`lifetime_hours` accepts `1`, `5`, `12`, `24`, `48`, `72`, or `168` (1 week).

`status` returns JSON including file IDs. Actions use these IDs, not filenames:

```bash
~/.local/bin/transist action pin FILE_ID
~/.local/bin/transist action unpin FILE_ID
~/.local/bin/transist action restore FILE_ID
```

`transist tick` runs one real cleanup cycle immediately. Use it only when you intend to process any overdue files.

If `transist` is not found in your shell, use the full `~/.local/bin/transist` path or add `~/.local/bin` to your PATH.

## Uninstall or upgrade

From the extracted source folder:

```bash
python3 install.py --uninstall
```

Uninstall stops cleanup and removes program files, launcher, and extension. It **preserves your active files, recovery copies, and database**. Reinstalling reconnects to those deadlines, so overdue files may then be processed. To upgrade, run the new version's installer; it replaces program files while preserving data.

## Development and verification

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q transist install.py
node --input-type=module --check < extension/extension.js
node --input-type=module --check < extension/prefs.js
node --test tests/*.test.mjs
python3 build.py
```

Core tests use isolated temporary directories and an injected clock; they never wait five hours or touch your real files. See [VALIDATION.md](VALIDATION.md) for completed checks and the remaining live desktop checks.

## Publish on GitHub and the extension store

This source is ready to put into a GitHub repository; it has **not been published** by the build process. `python3 build.py` creates a source archive and a separate GNOME extension ZIP under `dist/`.

Before a public release:

1. Run the live desktop checks in `VALIDATION.md` on each advertised GNOME version; trim `shell-version` to the versions you actually support.
2. Choose the final extension UUID and update the installer and documentation consistently if it changes. Add your real repository URL to `extension/metadata.json`; no unverified URL is prefilled.
3. Add actual screenshots/demo media from the running extension preferences and describe the separately installed background-service dependency clearly.
4. Review and understand the implementation, then publish your repository and a tagged release containing the source archive.
5. Submit **only the extension ZIP** to GNOME Extensions for review. The headless cleanup service is installed separately from your release; extension-store installation alone cannot install or start it.

GNOME's current rules require reviewable code and maintainership and restrict AI-generated submissions. The generated JavaScript includes the maintainer notice specified by GNOME's guidance. It must not be submitted unchanged as an unreviewed AI-generated extension. Store acceptance is **not guaranteed**. Read the [review guidelines](https://gjs.guide/extensions/review-guidelines/review-guidelines.html) and [maintainer guidance](https://gjs.guide/extensions/review-guidelines/best-practices.html) before submission. Reference: [GNOME extension development](https://gjs.guide/extensions/development/creating.html).

MIT licensed. Contributions and bug reports should include the desktop, GNOME version if applicable, Python version, and relevant service error messages. Remove private filenames from logs before sharing.
