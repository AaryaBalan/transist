"""One-time compatibility bridge for installations using the previous name."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess

OLD = 'transist'
NEW = 'transit'
OLD_UUID = OLD + '@aaryabalan.local'


def prepare(home, data, config):
    """Move storage without rewriting database rows, deadlines, or file contents."""
    old_root, new_root = home / ('_' + OLD), home / ('_' + NEW)
    old_data, new_data = data / OLD, data / NEW
    extensions = home / '.local/share/gnome-shell/extensions'
    old_extension = extensions / OLD_UUID
    moves = [(old_root, new_root), (old_data, new_data)]
    # Validate every collision before stopping anything or moving user data.
    for source, target in moves:
        if os.path.lexists(source):
            if source.is_symlink() or not source.is_dir():
                raise ValueError(f'Refusing unsafe migration source: {source}')
            if os.path.lexists(target):
                raise ValueError(f'Both {source} and {target} exist. Move one aside before upgrading; nothing was merged.')
    vault_root = old_root if old_root.exists() else new_root
    old_vault, new_vault = vault_root / ('.' + OLD + '-recovery'), vault_root / ('.' + NEW + '-recovery')
    if os.path.lexists(old_vault):
        if old_vault.is_symlink() or not old_vault.is_dir() or os.path.lexists(new_vault):
            raise ValueError('Recovery directories conflict or are unsafe; migration has not changed any files.')
    direct = None
    if old_extension.is_dir():
        if not shutil.which('gnome-extensions'):
            raise ValueError('Disable the old GNOME extension before migrating on a GNOME desktop.')
        subprocess.run(['gnome-extensions', 'disable', OLD_UUID], check=True)
        if shutil.which('gsettings') and (old_extension / 'schemas/gschemas.compiled').exists():
            result = subprocess.run(['gsettings', '--schemadir', str(old_extension / 'schemas'),
                                     'get', 'org.gnome.shell.extensions.' + OLD, 'direct-screenshots'],
                                    capture_output=True, text=True, check=True)
            if result.stdout.strip() in ('true', 'false'):
                direct = result.stdout.strip()
    if (config / ('systemd/user/' + OLD + '.service')).exists():
        subprocess.run(['systemctl', '--user', 'disable', '--now', OLD + '.service'], check=True)
    # A running CLI operation must finish before the database directory moves.
    lock = None
    if old_data.exists():
        lock = os.open(old_data / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        for source, target in moves:
            if source.exists():
                source.rename(target)
        old_vault = new_root / ('.' + OLD + '-recovery')
        if old_vault.exists():
            old_vault.rename(new_root / ('.' + NEW + '-recovery'))
    finally:
        if lock is not None:
            os.close(lock)
    return direct


def finish(home, data, config):
    """Retire only the former program files after the renamed app is installed."""
    for path in (home / ('.local/bin/' + OLD),
                 config / ('systemd/user/' + OLD + '.service'),
                 data / ('applications/io.github.' + OLD + '.App.desktop'),
                 data / ('icons/hicolor/scalable/apps/io.github.' + OLD + '.App.svg'),
                 data / ('nautilus-python/extensions/' + OLD + '_guard.py'),
                 data / ('nautilus-python/extensions/' + OLD + '_guard_native.so')):
        path.unlink(missing_ok=True)
    for path in (data / (OLD + '-app'), home / '.local/share/gnome-shell/extensions' / OLD_UUID):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
