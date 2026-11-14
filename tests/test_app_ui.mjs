// Offline UI regression checks. Run: node --test tests/test_app_ui.mjs
// Uses an installed Edge/Chromium; set GOGGLES_UI_BROWSER to override its path.
import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const browser = process.env.GOGGLES_UI_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const available = existsSync(browser);
const page = pathToFileURL(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../goggles_bridge/app/ui/index.html'));
const captures = process.env.GOGGLES_UI_SCREENSHOTS;
const errors = [];
let processHandle, profile, socket, sequence = 0;
const pending = new Map(), events = new Map();

async function until(check, description) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await check()) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${description}`);
}
function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
function event(method) {
  return new Promise(resolve => events.set(method, resolve));
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  assert.equal(result.exceptionDetails, undefined, JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function open(query = '', width = 1120, height = 740) {
  await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  const loaded = event('Page.loadEventFired');
  await call('Page.navigate', { url: `${page}?demo&${query}` });
  await loaded;
  await until(() => evaluate("document.querySelector('#version').textContent.includes('0.3.2')"), 'UI ready');
}
async function capture(name) {
  if (!captures) return;
  await mkdir(captures, { recursive: true });
  const { data } = await call('Page.captureScreenshot', { format: 'png' });
  await writeFile(path.join(captures, `${name}.png`), Buffer.from(data, 'base64'));
}
const visible = key => evaluate(`!document.querySelector('[data-option="${key}"]').hidden`);
const uiTest = (name, run) => test(name, { skip: !available }, run);

before(async () => {
  if (!available) return;
  profile = await mkdtemp(path.join(tmpdir(), 'goggles-ui-'));
  processHandle = spawn(browser, ['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  const portFile = path.join(profile, 'DevToolsActivePort');
  await until(() => existsSync(portFile), 'browser debugger');
  const port = (await readFile(portFile, 'utf8')).split('\n')[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      message.error ? request.reject(new Error(message.error.message)) : request.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
    if (events.has(message.method)) {
      events.get(message.method)(message.params);
      events.delete(message.method);
    }
  });
  await call('Page.enable');
  await call('Runtime.enable');
  await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
});
after(async () => {
  if (!available) return;
  if (socket?.readyState === WebSocket.OPEN) await call('Browser.close').catch(() => {});
  socket?.close();
  processHandle?.kill();
  if (profile) {
    assert.equal(path.dirname(profile), path.resolve(tmpdir()));
    assert.ok(path.basename(profile).startsWith('goggles-ui-'));
    await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

uiTest('physical desktop retains every upstream advanced control', async () => {
  await open();
  for (const key of ['source', 'resolution', 'auto_start', 'preset', 'fps', 'bitrate_mbps']) assert.equal(await visible(key), true, key);
  for (const key of ['capture', 'keyframe_seconds', 'h264_profile', 'adaptive_quant', 'low_latency', 'usb_write_size']) assert.equal(await visible(key), true, key);
  assert.equal(await evaluate("document.querySelector('#opt-source option[value=virtual]').textContent"), 'Virtual Display');
  assert.deepEqual(await evaluate("[...document.querySelector('#opt-capture').options].map(o => o.value)"), ['gfxcapture', 'ddagrab']);
  assert.equal(await evaluate("document.querySelector('#opt-bitrate_mbps option').textContent"), 'Automatic (32 Mbps)');
  await capture('windows-display');
});

uiTest('logical separate display is selectable before it exists and uses selected resolution', async () => {
  await open('state=novirtual');
  assert.equal(await visible('display_index'), false);
  for (const key of ['capture', 'keyframe_seconds', 'h264_profile', 'adaptive_quant', 'low_latency']) assert.equal(await visible(key), false, key);
  for (const key of ['preset', 'usb_write_size']) assert.equal(await visible(key), true, key);
  assert.equal(await evaluate("document.querySelector('#action').textContent"), 'Install display driver');
  await evaluate("document.querySelector('#action').click()");
  await until(() => evaluate("document.querySelector('#action').textContent === 'Installing…'"), 'installation status');
  assert.equal(await evaluate("document.querySelector('#action').disabled && document.querySelector('#options').disabled"), true);
  await capture('windows-installing');
  await until(() => evaluate("document.querySelector('#action').textContent === 'Start streaming'"), 'installation complete');
  await open('state=streaming&virtual&720p', 940, 660);
  assert.match(await evaluate("document.querySelector('#subline').textContent"), /^1280 × 720 at 100 fps and 32 Mbps/);
  assert.equal(await evaluate("document.querySelector('#checks').children.length"), 4);
  assert.equal(await evaluate("document.querySelector('.settings').scrollWidth <= document.querySelector('.settings').clientWidth"), true);
  await capture('windows-virtual-small');
});

uiTest('switching virtual screen preserves physical advanced preferences and focus', async () => {
  await open();
  await evaluate("window.demoBackend.set_options({capture:'gfxcapture',keyframe_seconds:1,h264_profile:'baseline',adaptive_quant:true,low_latency:false,usb_write_size:2048})");
  await evaluate("document.querySelector('#opt-source').value='virtual'; document.querySelector('#opt-source').dispatchEvent(new Event('change'))");
  await until(() => evaluate("document.querySelector('[data-option=capture]').hidden"), 'virtual restrictions');
  const expected = {capture:'gfxcapture', keyframe_seconds:1, h264_profile:'baseline', adaptive_quant:true, low_latency:false, usb_write_size:2048};
  assert.deepEqual(await evaluate("window.demoBackend.snapshot().then(s => Object.fromEntries(['capture','keyframe_seconds','h264_profile','adaptive_quant','low_latency','usb_write_size'].map(k => [k,s.options[k]])))"), expected);
  await evaluate("document.querySelector('#opt-source').value='display'; document.querySelector('#opt-source').dispatchEvent(new Event('change'))");
  await until(() => evaluate("!document.querySelector('[data-option=capture]').hidden && document.querySelector('#opt-capture').value==='gfxcapture'"), 'restored capture preference');
  assert.equal(await evaluate("document.querySelector('#opt-h264_profile').value"), 'baseline');
  assert.equal(await evaluate("document.querySelector('#opt-keyframe_seconds').value"), '1');
  assert.equal(await evaluate("document.querySelector('[data-option=adaptive_quant] input').checked"), true);
  assert.equal(await evaluate("document.querySelector('[data-option=low_latency] input').checked"), false);
  await open('', 940, 660);
  assert.equal(await evaluate("document.querySelector('.settings').scrollWidth <= document.querySelector('.settings').clientWidth"), true);
  await capture('windows-advanced-small');
});

uiTest('automatic bitrate follows frame rate and display selection saves a stable device', async () => {
  await open();
  await evaluate("document.querySelector('input[name=fps][value=\"60\"]').click()");
  await until(() => evaluate("document.querySelector('#opt-bitrate_mbps option').textContent === 'Automatic (24 Mbps)'"), '60 fps automatic bitrate');
  await evaluate("document.querySelectorAll('#display-picker button')[1].click()");
  await until(() => evaluate("window.demoBackend.snapshot().then(s => s.options.display_device === s.displays[1].device)"), 'stable display selection');
  await evaluate("window.savedBitrateControl = document.querySelector('#opt-bitrate_mbps'); window.savedBitrateControl.focus()");
  await delay(600);
  assert.equal(await evaluate("document.activeElement === window.savedBitrateControl && !document.querySelector('#options').disabled"), true);
});

uiTest('a disconnected saved display remains unselected and the only remaining display can be chosen', async () => {
  await open('single&missingdisplay');
  assert.equal(await evaluate("document.querySelector('#headline').textContent"), 'The selected display is disconnected');
  assert.equal(await evaluate("document.querySelector('#action').disabled"), true);
  assert.equal(await evaluate("document.querySelectorAll('#display-picker button').length"), 1);
  assert.equal(await evaluate("document.querySelector('#display-picker button').getAttribute('aria-checked')"), 'false');
  await evaluate("document.querySelector('#open-guide').click()");
  assert.equal(await evaluate("document.querySelector('#guide-title').textContent"), 'Choose a display');
  await evaluate("document.querySelector('#guide-skip').click(); document.querySelector('#display-picker button').click()");
  await until(() => evaluate("window.demoBackend.snapshot().then(s => s.options.display_device === s.displays[0].device)"), 'replacement display selection');
  assert.equal(await evaluate("document.querySelector('#action').disabled"), false);
  assert.equal(await evaluate("document.querySelectorAll('#display-picker button').length"), 0);
});

uiTest('setup guide includes source choice, display installation and official DJI entry', async () => {
  await open('state=novirtual&step=source');
  assert.equal(await evaluate("document.querySelector('#guide-source-row').hidden"), false);
  await evaluate("document.querySelector('#guide-action').click()");
  await until(() => evaluate("document.querySelector('#guide-title').textContent === 'Set up the separate display'"), 'virtual driver guide step');
  await open('state=nodriver&step=driver');
  assert.equal(await evaluate("document.querySelector('#guide-help').hidden"), false);
  assert.equal(await evaluate("document.querySelector('#guide-action').textContent"), 'Install DJI driver');
  await capture('windows-driver-guide');
});

uiTest('preparing, stopping and installation failures have actionable stable states', async () => {
  await open('state=preparing');
  assert.equal(await evaluate("document.querySelector('#headline').textContent"), 'Preparing the separate display');
  await open('state=stopping&virtual');
  assert.equal(await evaluate("document.querySelector('#action').disabled"), true);
  assert.equal(await evaluate("document.querySelector('#action').textContent"), 'Stopping…');
  await open('state=installerror');
  assert.match(await evaluate("document.querySelector('#subline').textContent"), /cancelled/);
  assert.equal(await evaluate("document.querySelector('#action').disabled"), false);
  await capture('windows-install-error');
});

uiTest('mac retains the upstream settings and onboarding without windows capabilities', async () => {
  await open('mac');
  for (const key of ['source', 'resolution', 'auto_start', 'capture', 'preset', 'adaptive_quant']) assert.equal(await visible(key), false, key);
  for (const key of ['display_index', 'fps', 'keyframe_seconds', 'h264_profile', 'low_latency', 'usb_write_size']) assert.equal(await visible(key), true, key);
  assert.equal(await evaluate("document.querySelector('#checks').children.length"), 3);
  await capture('mac-display');
  await open('mac&step=welcome');
  assert.equal(await evaluate("document.querySelector('#dots').children.length"), 6);
  assert.deepEqual(errors, []);
});
