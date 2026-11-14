// fake backend so the window runs without goggles
// index.html?state=idle|unplugged|nodriver|noscreen|untested|waiting|streaming|error holds one state, state=fresh is a first run,
// state=update offers a newer release. Add &mac to see the Mac window.
// Add &virtual for a separate display, &720p for 720p, or state=novirtual|installing|installerror|preparing|stopping.
// Add &single&missingdisplay to recover a disconnected saved display with only one display remaining.
(() => {
  'use strict';
  const params = new URLSearchParams(location.search), frozen = params.get('state'), mac = params.has('mac');
  const displays = [
    { index: 0, device: '\\\\.\\DISPLAY1', name: 'Display 1', x: 0, y: 0, width: 2560, height: 1600, hz: 240, primary: true },
    { index: 1, device: '\\\\.\\DISPLAY2', name: 'Display 2', x: 2560, y: 260, width: 1920, height: 1080, hz: 60, primary: false },
  ];
  if (params.has('single')) displays.splice(1);
  const bitrates = {
    60: { allowed: [8, 10, 12, 16, 20, 24], auto: 24 }, 75: { allowed: [8, 10, 12, 16, 20, 24, 30], auto: 30 },
    90: { allowed: [8, 10, 12, 16, 20, 24, 30, 32], auto: 32 }, 100: { allowed: [8, 10, 12, 16, 20, 24, 30, 32, 40], auto: 32 },
  };
  const tested_versions = ['01.11.00.00', '01.14.00.00'];
  const device = frozen === 'untested'
    ? { model: 'DJI Goggles 2', identity: 'E3T ZV900 AC Feb 26 2025|12:39:57', build: 'Feb 26 2025', version: null, tested: false, tested_versions }
    : { model: 'DJI Goggles 2', identity: 'E3T ZV900 AC Dec 24 2024|12:34:04', build: 'Dec 24 2024', version: '01.11.00.00', tested: true, tested_versions };
  const state = {
    app: { name: 'Goggles Bridge', version: '0.3.1', platform: mac ? 'darwin' : 'win32', updatable: true },
    capabilities: mac ? {} : { virtual_display: true, resolution: true, auto_start: true, captures: ['gfxcapture', 'ddagrab'], fixed_encoder_options: false },
    checks: { driver: { needed: !mac, ok: mac || frozen !== 'nodriver' }, screen: { needed: mac, ok: !mac || frozen !== 'noscreen' },
      ffmpeg: { needed: !mac, ok: true },
      virtual_display: { needed: !mac, installed: !['novirtual', 'installing', 'installerror'].includes(frozen),
        ok: !['novirtual', 'installing', 'installerror'].includes(frozen), needs_update: false, installing: frozen === 'installing',
        problem: frozen === 'installerror' ? 'Installation was cancelled. Try again and approve the Windows prompt.' : null },
      attached: !['unplugged', 'fresh'].includes(frozen) },
    displays,
    options: { fps: 100, bitrate_mbps: null, capture: mac ? 'screencapturekit' : 'ddagrab', display_index: 0, show_cursor: true, preset: 'p1',
      keyframe_seconds: mac ? 3 : 0, low_latency: true, usb_write_size: 16384, h264_profile: 'high', adaptive_quant: false,
      ...(!mac ? { source: params.has('virtual') || ['novirtual', 'installing', 'installerror', 'preparing'].includes(frozen) ? 'virtual' : 'display',
        resolution: params.has('720p') ? '720p' : '1080p', auto_start: false,
        display_device: params.has('missingdisplay') ? 'DISCONNECTED' : displays[0].device } : {}) },
    choices: { fps: [60, 75, 90, 100], capture: mac ? ['screencapturekit'] : ['gfxcapture', 'ddagrab'], preset: ['p1', 'p4'], keyframe_seconds: mac ? [1, 3] : [0, 1, 3],
      h264_profile: ['baseline', 'high'], usb_write_size: [2048, 16384], bitrates },
    frame_limit: 56000, phase: 'idle', problem: null, device: ['unplugged', 'fresh', 'nodriver', 'noscreen'].includes(frozen) ? null : device,
    stats: null, oversize: 0, log: null,
    onboarded: frozen !== 'fresh',
  };
  let timers = [], ticker;

  const tick = () => { state.stats = { fps: state.options.fps - Math.random(), send_ms_p95: .6 + Math.random() * .2, frame_bytes_max: 41000 + Math.random() * 4000 }; };
  function stream() {
    Object.assign(state, { phase: 'streaming', problem: null, device });
    tick();
    ticker = setInterval(tick, 5000);
  }
  function halt() {
    timers.forEach(clearTimeout);
    clearInterval(ticker);
    timers = [];
  }
  const after = (ms, change) => timers.push(setTimeout(change, ms));

  if (frozen === 'fresh') setTimeout(() => { state.checks.attached = true; state.device = device; }, 9000);
  else if (frozen === 'streaming') stream();
  else if (frozen === 'waiting') Object.assign(state, { phase: 'waiting', problem: { code: 'virtual_flight', message: '' } });
  else if (frozen === 'error') Object.assign(state, { phase: 'error', device, problem: { code: 'rejected', message: 'Goggles rejected 0b/1a: d6' } });
  else if (['preparing', 'stopping'].includes(frozen)) state.phase = frozen;

  function installDriver(kind) {
    if (!['idle', 'error'].includes(state.phase)) return { error: 'Stop streaming before installing a driver.' };
    const check = state.checks[kind];
    Object.assign(check, { installing: true, problem: null });
    after(2000, () => Object.assign(check, { ok: true, installed: true, needs_update: false, installing: false }));
    return { ok: true };
  }

  window.demoBackend = {
    snapshot: async () => {
      const snapshot = JSON.parse(JSON.stringify(state));
      if (!mac) {
        const virtual = snapshot.options.source === 'virtual';
        snapshot.capabilities.fixed_encoder_options = virtual;
        snapshot.capabilities.captures = virtual ? ['ddagrab'] : ['gfxcapture', 'ddagrab'];
        snapshot.choices.capture = snapshot.capabilities.captures;
      }
      return snapshot;
    },
    set_options: async options => {
      if (!['idle', 'error'].includes(state.phase)) return { error: 'Stop streaming before changing settings.' };
      const next = { ...state.options, ...options };
      if (next.bitrate_mbps !== null && !bitrates[next.fps].allowed.includes(next.bitrate_mbps)) {
        return { error: `At ${next.fps} fps, use at most ${bitrates[next.fps].allowed.at(-1)} Mbps.` };
      }
      state.options = next;
      return { ok: true };
    },
    start: async () => {
      if (!state.checks.driver.ok || (state.options.source === 'virtual' && !state.checks.virtual_display.ok)) {
        return { error: 'Install the required driver first.' };
      }
      halt();
      Object.assign(state, { phase: state.options.source === 'virtual' ? 'preparing' : 'checking', problem: null, stats: null });
      after(700, () => Object.assign(state, { phase: 'waiting', problem: { code: 'virtual_flight', message: '' } }));
      after(3600, () => Object.assign(state, { phase: 'connecting', problem: null }));
      after(4100, () => Object.assign(state, { phase: 'ready', device }));
      after(4700, stream);
      return { ok: true };
    },
    stop: async () => {
      halt();
      Object.assign(state, { phase: 'stopping', problem: null, stats: null });
      after(600, () => { state.phase = 'idle'; });
      return { ok: true };
    },
    finish_setup: async () => { state.onboarded = true; return { ok: true }; },
    diagnostics: async () => 'Goggles Bridge demo',
    open_link: async () => ({ ok: true }),
    install_driver: async () => installDriver('driver'),
    install_virtual_driver: async () => installDriver('virtual_display'),
    check_update: async () => ({ version: frozen === 'update' ? '0.3.2' : null }),
    install_update: () => new Promise(done => setTimeout(() => done({ error: "Couldn't install the update" }), 3000)),
  };
})();
