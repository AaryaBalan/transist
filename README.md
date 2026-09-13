# Transist — GNOME Extension

**Files, recovery history, and settings in one native preferences window.**

Drop any regular file directly into `~/_transist`. It expires after five hours,
remains recoverable for seven days, and can be restored for another five hours
or marked permanent.

## Native preferences update

There is **no separate Transist desktop app**. Open GNOME Extensions → Transist →
Settings, or choose **Files, History & Settings** from the top-bar menu.

The preferences window contains:

- **Active Files:** search filenames, view countdowns, keep permanently, or make temporary.
- **Recently Deleted:** search history and restore eligible files.
- **Settings:** screenshot capture, screenshot folder, pause, and service status.

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
3. In **Active Files**, select **Keep Permanently** or **Make Temporary**.
4. In **Recently Deleted**, select **Restore · 5 hours** during the recovery window.
5. In **Settings**, enable screenshot capture and edit its source folder. Click
   the entry's apply/check button to save the folder.
6. Use each page's filename search; lists load 100 entries at a time with **Show more**.

Missing backend and operation failures appear in preferences, rather than silently
opening another app. The UI refreshes every ten seconds and performs backend calls
asynchronously. Closing preferences stops its polling; already-started file
operations may finish safely in the background.

### Screenshot behavior

By default the source is the XDG Pictures folder's `Screenshots` subfolder, usually `~/Pictures/Screenshots`. If your screenshot tool uses another folder, enter its dedicated screenshot directory in Settings and click **Save folder**. New PNG, JPEG, WebP, AVIF, BMP, and TIFF files in that folder are eligible.

Transist **moves newly detected images after they have been unchanged for 30 seconds**. It does not patch GNOME's screenshot internals or change other apps' save settings. The original screenshot notification may still point to its old path after the move; use Transist to open the folder. Existing images at the time capture is enabled are left alone. Turning capture off and on establishes a new baseline. Any new image in the selected source directory is treated as a screenshot, so use a dedicated folder.

Other screenshot programs can also be configured to save directly into `~/_transist`; those files receive timers without the capture setting. Screen recordings and documents placed directly into `_transist` work like all other regular files. The capture setting does not watch the Videos folder.

### Exact lifetime rules

| Event | Result |
| --- | --- |
| File first detected directly in `_transist` | Five-hour timer starts |
| Five-hour deadline reached | Moves to hidden private recovery storage on the next cleanup cycle |
| Restore within seven days of that move | Returns to `_transist` with a fresh five hours |
| Same name already exists on restore | Restored file gets a unique suffix; existing item remains untouched |
| Keep permanently | File stays in place with no expiry |
| Make temporary | New five-hour timer starts |
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
- Disabling the GNOME extension removes the top-bar UI only. To stop cleanup, use Settings → Pause, or stop the service.

## Service and command line

```bash
systemctl --user status transist.service
journalctl --user -u transist.service -n 50
systemctl --user stop transist.service
systemctl --user start transist.service

~/.local/bin/transist status
~/.local/bin/transist config paused true
~/.local/bin/transist config paused false
~/.local/bin/transist config capture_screenshots true
~/.local/bin/transist config screenshot_folder "$HOME/Pictures/Screenshots"
```

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
node --test tests/preferences.test.mjs
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
