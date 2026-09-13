# Validation — folder deletion protection and recovery availability

## Completed

- **46 Python tests passed:** deletion/moving of the root or recovery folder,
  immediate availability checks, returned/replaced/symlinked recovery copies,
  all seven cleanup windows, changing existing timers,
  pause/resume, persistence, restoration, collision handling, recovery deadlines,
  permanent files, screenshot capture, crash reconciliation, installer, and CLI settings.
- Real GIO tests verify exact-root Trash/delete rejection, unchanged child contents,
  unrelated-folder and child deletion, disable/re-enable, Nautilus recursive-delete
  behavior, and restoration of original native methods. A backend test verifies
  deliberate folder removal is respected until re-enabling. Native dispatcher tests
  verify service-stop success/failure and the removal marker.
- **10 JavaScript tests passed:** unavailable recovery entries, active/history actions, search, recovery cutoff,
  literal filenames, time labels, all seven restore labels, integration source checks,
  translated screenshot paths, and unrelated-path preservation.
- An isolated D-Bus/GNOME Files 50 session using a temporary HOME verified both
  Trash and permanent Delete are blocked before changing sample contents, normal
  Trash works for a child and unrelated folder, and disabling releases root Trash.
  The actual restriction popup was rendered and visually inspected: one Close
  button and the instruction to disable Transist. No real user files were deleted.
- Installed into the live desktop: Transist reports ACTIVE, its cleanup service is
  active, and the restarted Files process maps `transist_guard_native.so`.
- Native dispatcher compilation passed with `-Wall -Wextra -Werror`.
- Python compilation and JavaScript module syntax checks passed.
- Local GJS introspection confirmed ComboRow, StringList, and accessible-label APIs.
- A native GTK smoke run with sample files verified equal action-button widths and
  identical eye-button X positions. Active Files, Settings, and Credits were rendered
  and visually inspected. All four tab titles fit at the new default window width.
- The folder-safety warning and missing-recovery history state were rendered and
  visually inspected with sample data, including the disabled Unavailable button
  and Open Trash action.
- GSettings schemas compile with strict validation and are included by installer/build.
- Archive integrity checks passed.

The installer test simulates an upgrade from the old desktop app. It verifies
that the old launcher and GUI sources are removed, the headless command works
without PyGObject, and user files/history survive upgrade and uninstall.

The opt-in native test is `dbus-run-session -- python3 tests/nautilus_smoke.py`.
It uses a temporary HOME and refuses an existing GNOME desktop bus.

## Not verified in this environment

Direct screenshot saving still needs an end-to-end check after logging out/in to
load the new Shell code. Its directory construction was checked against the installed
GNOME 50.1 screenshot implementation; other advertised versions need live testing.
Opening files and Credits links in their default applications still needs a live check.
The systemd operations are mocked in installer tests. GitHub CI has not been run.

## Live checks before publishing

- Close the old app, install this update, and log out/in. Confirm the Transist
  application-menu entry disappears and only the GNOME extension UI remains.
- Open preferences through GNOME Extensions, the Shell menu, and
  `gnome-extensions prefs transist@aaryabalan.local`.
- Confirm Active Files, Recently Deleted, Settings, and Credits appear in one window.
- With a disposable test installation, use a terminal to move/delete `_transist` and confirm a
  storage-removal notification, an Open Trash warning, no stale Active Files entries,
  and Unavailable recovery entries. Confirm the warning does not claim to prevent
  filesystem deletion. Never use real files for destructive verification.
- Enable direct saving after logout/login, take a GNOME screenshot, and confirm it
  appears immediately only in `_transist` and its notification opens that file.
  Turn the toggle off and confirm GNOME uses its normal folder. Test filename
  collisions, translated folder names, and extension disable/re-enable.
- Change GNOME's system appearance between light and dark. Verify native controls
  and text; no Transist-specific stylesheet or palette should override it.
- Test search, no-results state, long/unusual filenames, keyboard navigation,
  narrow windows, and Show more with over 100 entries.
- Select each cleanup window (1, 5, 12, 24, 48, 72 hours, 1 week). Confirm countdowns
  and restore labels update, the selection survives reopening, and shorter windows
  apply to elapsed time without resetting timers.
- Exercise pin/unpin and restore with disposable samples. Confirm a new timer using
  the selected window and no overwrite when a filename already exists.
- Click the eye icon on temporary and permanent files, including spaces, Unicode,
  and special characters in filenames. Confirm the correct default app opens;
  unavailable files or missing app associations should show an error toast.
- Test capture toggle, folder apply, pause, service status, and error messages.
  Periodic refresh must not overwrite a folder edit that has not been applied.
- Close preferences during an operation and reopen. Confirm the operation completes
  or is safely reconciled; no repeated polling remains after the window closes.
- Confirm cleanup continues when preferences close or the Shell icon is disabled.
  After disabling and deleting the root through Files, confirm cleanup stops and
  re-enabling resumes it. Test this only with disposable files.
- Test missing/stopped service and recovery after reinstall/restart.
- Recheck each declared GNOME version before advertising compatibility.
