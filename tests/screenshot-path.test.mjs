import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../extension/screenshot-path.js', import.meta.url), 'utf8');
const {screenshotPath} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('redirects GNOME screenshot directory including translated names and custom Pictures', () => {
    assert.equal(screenshotPath(['/home/user/Pictures', 'Screenshots'], '/home/user/Pictures', 'Screenshots', '/home/user/_transit'), '/home/user/_transit');
    assert.equal(screenshotPath(['/media/My Photos', 'Captures d’écran'], '/media/My Photos', 'Captures d’écran', '/home/user/_transit'), '/home/user/_transit');
});

test('leaves pictures, recordings, filenames, and unrelated paths untouched', () => {
    for (const parts of [[], ['/home/user/Pictures'], ['/home/user/Videos', 'Screencasts'], ['/elsewhere', 'Screenshots'], ['/home/user/Pictures', 'Screenshots', 'shot.png'], ['/home/user/_transit', 'shot.png']])
        assert.equal(screenshotPath(parts, '/home/user/Pictures', 'Screenshots', '/home/user/_transit'), null);
});
