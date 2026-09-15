import argparse
import json
import logging
import signal
import shutil
import subprocess
import threading
from .core import Store


def main():
    parser = argparse.ArgumentParser(description='Transit: files for now, recovery for a week')
    commands = parser.add_subparsers(dest='command', required=True)
    gui = commands.add_parser('gui')
    gui.add_argument('--page', choices=['active', 'history', 'settings'], default='active')
    for name in ('status', 'tick', 'daemon', 'open', 'empty-trash'):
        commands.add_parser(name)
    action = commands.add_parser('action')
    action.add_argument('operation', choices=['pin', 'unpin', 'restore', 'delete'])
    action.add_argument('id')
    preview = commands.add_parser('preview')
    preview.add_argument('id')
    config = commands.add_parser('config')
    config.add_argument('key', choices=['paused', 'capture_screenshots', 'screenshot_folder', 'theme', 'lifetime_hours'])
    config.add_argument('value')
    args = parser.parse_args()
    if args.command == 'gui':
        # Compatibility alias: opens native extension preferences, never a desktop app.
        subprocess.run(['gnome-extensions', 'prefs', 'transit@aaryabalan.local'], check=True)
        return
    store = Store()
    if args.command == 'daemon':
        logging.basicConfig(level=logging.INFO)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        previous_error = None
        previous_missing = 0
        while not stop.is_set():
            try:
                with store.session() as s:
                    s.tick()
                    missing = s.missing_recovery_count()
                    storage_lost = s.storage_recreated or missing > previous_missing
                if storage_lost:
                    message = ('The _transit folder or recovery files were removed outside Transit. '
                               'Check system Trash. Before removing the folder intentionally, disable '
                               'the extension and stop transit.service; disabling the extension alone does not stop cleanup.')
                    logging.warning(message)
                    if shutil.which('notify-send'):
                        try:
                            subprocess.run(['notify-send', '--app-name=Transit', '--urgency=critical',
                                            'Transit storage was removed', message],
                                           timeout=3, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except (OSError, subprocess.TimeoutExpired):
                            pass
                previous_missing = missing
                previous_error = None
            except Exception as error:
                if str(error) != previous_error:
                    logging.exception('Cleanup paused for this cycle; files retained')
                    previous_error = str(error)
            stop.wait(10)
        return
    try:
        with store.session() as s:
            if args.command == 'tick':
                s.tick()
            elif args.command == 'preview':
                print(json.dumps(s.recovery_path(args.id)))
                return
            elif args.command == 'empty-trash':
                s.empty_trash()
            elif args.command == 'action':
                s.action(args.id, args.operation)
            elif args.command == 'config':
                value = args.value
                if args.key in ('paused', 'capture_screenshots'):
                    if value not in ('true', 'false'):
                        raise ValueError('Use true or false')
                    value = value == 'true'
                elif args.key == 'lifetime_hours':
                    value = int(value)
                s.configure(args.key, value)
            elif args.command == 'open':
                subprocess.Popen(['xdg-open', str(s.root)], start_new_session=True)
                return
            snapshot = s.snapshot()
        try:
            check = subprocess.run(['systemctl', '--user', 'is-active', 'transit.service'], capture_output=True, text=True, timeout=3)
            snapshot['service'] = check.stdout.strip() or 'unavailable'
        except (OSError, subprocess.TimeoutExpired):
            snapshot['service'] = 'unavailable'
        print(json.dumps(snapshot))
    except (OSError, ValueError) as error:
        parser.exit(1, f'Transit: {error}\n')


if __name__ == '__main__':
    main()
