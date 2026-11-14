(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const SVG = 'http://www.w3.org/2000/svg';
  const CAPTURE = {
    gfxcapture: 'Windows Graphics Capture', ddagrab: 'Desktop Duplication',
    screencapturekit: 'ScreenCaptureKit', avfoundation: 'AVFoundation',
  };
  const NAMES = {
    source: { display: 'Computer display', virtual: 'Virtual Display' },
    resolution: { '720p': '1280 × 720', '1080p': '1920 × 1080' },
    capture: CAPTURE,
    keyframe_seconds: { 0: 'On start only', 1: '1 second', 3: '3 seconds' },
    h264_profile: { high: 'High', baseline: 'Baseline' },
    preset: { p1: 'p1', p4: 'p4' },
    usb_write_size: { 16384: '16 KB', 2048: '2 KB' },
  };
  const BASIC = [
    { key: 'source', label: 'Source', kind: 'select', windows: true, capability: 'virtual_display',
      info: 'Use an existing display, or create a separate display for the goggles. The separate display is added when streaming starts and removed when it stops.' },
    { key: 'display_index', label: 'Display', kind: 'display' },
    { key: 'resolution', label: 'Resolution', kind: 'select', windows: true, capability: 'resolution' },
    { key: 'fps', label: 'Frame rate', kind: 'segment',
      info: 'Frames sent to the goggles each second. At the same bitrate, a higher frame rate leaves less data for each frame.' },
    { key: 'bitrate_mbps', label: 'Bitrate', kind: 'select',
      info: 'Video data sent each second. Automatic follows the frame rate: 24 Mbps at 60 fps, 30 Mbps at 75 fps, and 32 Mbps at 90 or 100 fps. At 100 fps, try 40 Mbps for fast motion and fine detail.' },
    { key: 'show_cursor', label: 'Mouse pointer', kind: 'switch' },
    { key: 'auto_start', label: 'Start on USB connection', kind: 'switch', windows: true, capability: 'auto_start',
      info: 'Start streaming when the goggles connect over USB, and stop when they disconnect. Open DJI Virtual Flight on the goggles first. Stopping manually keeps the stream stopped until the next connection.' },
  ];
  const ADVANCED = [
    { key: 'capture', label: 'Capture method', kind: 'select', windows: true,
      info: 'The method used to capture the selected display. Windows uses NVIDIA hardware encoding.' },
    { key: 'keyframe_seconds', label: 'Keyframe interval', kind: 'select',
      info: 'Time between complete pictures. On start only repeats complete pictures during startup, then avoids periodic refresh. The 1 and 3 second options repeat them throughout the stream.' },
    { key: 'h264_profile', label: 'H.264 profile', kind: 'select',
      info: 'High compresses more efficiently. Baseline is simpler to decode.' },
    { key: 'preset', label: 'Encoder preset', kind: 'select', windows: true,
      info: 'p1 encodes fastest. p4 keeps more fine detail and takes longer.' },
    { key: 'adaptive_quant', label: 'Adaptive quantization', kind: 'switch', windows: true,
      info: 'Gives detailed areas of each frame more data. Its effect on delay is unmeasured.' },
    { key: 'low_latency', label: 'Low-latency delivery', kind: 'switch',
      info: 'Sends each frame as soon as it is encoded. Turn it off only to troubleshoot.' },
    { key: 'usb_write_size', label: 'USB write size', kind: 'select',
      info: 'The most data sent in one USB write. 16 KB is the tested default.' },
  ];
  // headline and recovery for each problem the engine reports
  const PROBLEMS = {
    virtual_flight: ['Waiting for DJI Virtual Flight', 'On the goggles, go to More > DJI Virtual Flight. Streaming starts when it opens.'],
    unplugged: ['Goggles disconnected', 'Reconnect the cable. Streaming resumes when the goggles are back.'],
    slow_link: ['The USB connection is too slow', 'Unplug the cable and plug it in again. If it repeats, try another port or cable.'],
    rejected: ['The goggles refused the stream', 'On the goggles, leave Virtual Flight and open it again. Then start streaming.'],
    unsupported: ['These goggles are not supported', 'Goggles Bridge supports DJI Goggles 2 and DJI Goggles Integra.'],
    oversize: ['Frames are too large for the goggles', 'Select a lower bitrate, and then start streaming.'],
    no_video: ['The display stopped sending frames', 'Check that the display is on, and then start streaming.'],
    encoder: ['Screen capture failed', null],
    virtual_display: ['The separate display could not start', 'Open the setup guide to check the virtual display driver, and then try again.'],
    other: ['Streaming stopped', null],
  };
  const BUSY = { checking: ['Starting', 'Checking screen capture.'], connecting: ['Connecting to the goggles', ''],
    preparing: ['Preparing the separate display', 'Adding the display and applying the selected resolution and refresh rate.'],
    stopping: ['Stopping', 'Finishing the stream and removing its separate display.'],
    ready: ['Connecting to the goggles', ''] };
  const GUIDE = {
    welcome: ['Your screen, in your goggles', 'Goggles Bridge sends this computer’s screen to DJI Goggles 2 or DJI Goggles Integra over a USB cable.'],
    driver: ['Install the DJI USB driver', 'Install DJI Assistant 2 (Consumer Drones Series). It includes the USB driver for the goggles.'],
    screen: ['Allow screen recording', 'Goggles Bridge needs permission to send this Mac’s screen. Turn it on in System Settings, and then reopen the app.'],
    cable: ['Connect the goggles', 'Use a USB-A to USB-C data cable, with the USB-A end in this computer. Then power the goggles on.'],
    source: ['Choose a screen source', 'Send an existing computer display, or use a separate display for the goggles so your main screen stays free.'],
    virtual_display: ['Set up the separate display', 'Install the virtual display driver once. The display is added when streaming starts and removed when it stops. Windows may ask you to approve the installation.'],
    display: ['Choose a display', 'The goggles show one display. Select the one to send.'],
    flight: ['Open DJI Virtual Flight', 'On the goggles, go to More > DJI Virtual Flight. Then start streaming.'],
    done: ['Streaming', 'Put the goggles on. To stop or change settings, return to this window.'],
  };
  const params = new URLSearchParams(location.search);
  const calm = matchMedia('(prefers-reduced-motion: reduce)');

  let api, snap, toastTimer, painted, updating, scenes = 0;
  const drawn = {}, controls = {};
  const guide = { open: false, step: 'welcome' };

  function el(tag, props = {}, ...children) {
    const node = props.svg ? document.createElementNS(SVG, tag) : document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === 'svg') continue;
      if (key === 'text') node.textContent = value;
      else if (key in node && !props.svg) node[key] = value;
      else node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  }
  // redraw a region only when its data changes, so focus and open menus survive polling
  function once(key, signature, draw) {
    const text = JSON.stringify(signature);
    if (drawn[key] !== text) { drawn[key] = text; draw(); }
  }
  function morph(change) {
    if (document.startViewTransition && !calm.matches) document.startViewTransition(change);
    else change();
  }
  function toast(text) {
    const node = $('#toast');
    node.textContent = text;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 2600);
  }
  const active = s => !['idle', 'error'].includes(s.phase);
  const capable = (s, name) => s.app.platform === 'win32' && Boolean(s.capabilities?.[name]);
  const virtual = s => capable(s, 'virtual_display') && s.options.source === 'virtual';
  const physicalDisplays = s => s.displays.filter(d => !d.virtual);
  const selectedDisplay = s => s.options.display_device
    ? physicalDisplays(s).find(d => d.device === s.options.display_device)
    : physicalDisplays(s).find(d => d.index === s.options.display_index) || physicalDisplays(s)[0];
  const needsDisplayPicker = s => physicalDisplays(s).length > 1 || (physicalDisplays(s).length === 1 && !selectedDisplay(s));
  const installing = s => Boolean(s.checks.driver.installing || s.checks.virtual_display?.installing);
  const visibleRow = (row, s) => {
    if (row.windows && s.app.platform !== 'win32') return false;
    if (row.capability && !capable(s, row.capability)) return false;
    if (row.key === 'display_index') return !virtual(s);
    if (row.key === 'capture' && (s.capabilities?.captures || s.choices.capture).length < 2) return false;
    return !(virtual(s) && ['capture', 'keyframe_seconds', 'h264_profile', 'adaptive_quant', 'low_latency'].includes(row.key));
  };
  const firmware = d => (d.version ? `Firmware ${d.version}` : `Firmware build ${d.build}`);
  const untested = d => `Firmware build ${d.build} hasn't been tested with Goggles Bridge.`;
  const start = () => api.start().then(refresh), stop = () => api.stop().then(refresh);
  const install = method => async () => {
    try {
      const result = await api[method]();
      if (result?.error) toast(result.error);
      await refresh();
    } catch (error) { toast(error.message || String(error)); }
  };
  const driverAction = (s, kind) => {
    const check = s.checks[kind], isVirtual = kind === 'virtual_display';
    const method = isVirtual ? 'install_virtual_driver' : 'install_driver';
    if (check.installing) return { label: 'Installing…', kind: 'start', disabled: true };
    if (!isVirtual && typeof api.install_driver !== 'function') {
      return { label: 'Get DJI Assistant 2', kind: 'start', run: () => api.open_link('driver') };
    }
    return { label: isVirtual ? (check.needs_update ? 'Update display driver' : 'Install display driver') : 'Install DJI driver',
      kind: 'start', run: install(method) };
  };

  // one drawing for every state: computer, cable, goggles
  function scene() {
    const id = `scene${++scenes}`;
    const desk = '<rect class="wall" width="200" height="126"/><rect class="win" x="16" y="14" width="104" height="70" rx="6"/>'
      + '<path class="line" d="M28 32h56M28 44h80M28 56h44"/><rect class="win" x="98" y="50" width="86" height="54" rx="6"/>'
      + '<path class="line" d="M110 68h46M110 80h60"/><rect class="dock" x="60" y="110" width="80" height="10" rx="5"/>'
      + '<path class="cursor" d="M0 0v16l4.2-3.8 2.8 6.3 2.6-1.2-2.7-6.1H12z"/>';
    const holder = el('div');
    holder.innerHTML = `<svg class="scene" viewBox="0 0 600 220" role="img">
      <defs>
        <clipPath id="${id}-screen"><rect x="50" y="34" width="200" height="126" rx="5"/></clipPath>
        <clipPath id="${id}-left"><circle cx="451.2" cy="105.8" r="25.4"/></clipPath>
        <clipPath id="${id}-right"><circle cx="530.4" cy="105.8" r="25.4"/></clipPath>
      </defs>
      <rect class="lid" x="40" y="24" width="220" height="146" rx="12"/>
      <g clip-path="url(#${id}-screen)"><g transform="translate(50 34)">${desk}</g></g>
      <rect class="base" x="16" y="172" width="268" height="12" rx="6"/>
      <path class="cable" d="M284 178C340 178 340 112 384 112"/>
      <circle class="pulse" r="4"/>
      <rect class="plug" x="384" y="104" width="16" height="16" rx="4"/>
      <path class="visor" d="M398.4 92.6c0-19.8 13.2-33 33-33h118.8c19.8 0 33 13.2 33 33V119c0 23.1-16.5 39.6-39.6 39.6-13.2 0-23.1-6.6-29.7-16.5l-6.6-9.9a19.8 19.8 0 0 0-33 0l-6.6 9.9c-6.6 9.9-16.5 16.5-29.7 16.5-23.1 0-39.6-16.5-39.6-39.6z"/>
      <circle class="lens" cx="451.2" cy="105.8" r="26.4"/><circle class="lens" cx="530.4" cy="105.8" r="26.4"/>
      <g class="view" clip-path="url(#${id}-left)"><g transform="translate(409.2 79.3) scale(.42)">${desk}</g></g>
      <g class="view" clip-path="url(#${id}-right)"><g transform="translate(488.4 79.3) scale(.42)">${desk}</g></g>
      <circle cx="451.2" cy="105.8" r="26.4"/><circle cx="530.4" cy="105.8" r="26.4"/>
      <g class="tag"><rect x="401" y="178" width="180" height="30" rx="15"/><text x="491" y="198">More &gt; DJI Virtual Flight</text></g>
      <g class="badge driver"><circle cx="258" cy="28" r="13"/><path d="M258 21v8M258 34.5v.2"/></g>
      <g class="badge fault"><circle cx="584" cy="58" r="13"/><path d="M584 51v8M584 64.5v.2"/></g>
    </svg>`;
    const svg = holder.firstElementChild;
    svg.style.setProperty('--len', `${$('.cable', svg).getTotalLength()}px`);
    return svg;
  }

  function model(s) {
    const o = s.options, c = s.checks, phase = s.phase, problem = s.problem || {};
    const display = selectedDisplay(s);
    const bitrate = o.bitrate_mbps ?? s.choices.bitrates[o.fps].auto;
    const live = phase === 'streaming', failed = phase === 'error';
    const fault = failed || phase === 'waiting' ? (PROBLEMS[problem.code] || PROBLEMS.other) : null;
    const cableFault = ['unplugged', 'slow_link'].includes(problem.code) && phase === 'waiting';

    let headline, subline, look, action = { label: 'Start streaming', kind: 'start', run: start };
    if (!c.driver.ok || c.driver.installing) {
      [headline, subline, look] = ['Install the DJI USB driver', c.driver.problem || GUIDE.driver[1], 'driver'];
      action = driverAction(s, 'driver');
    } else if (!c.screen.ok) {
      [headline, subline, look] = [...GUIDE.screen, 'driver'];
      action = { label: 'Open Settings', kind: 'start', run: () => api.open_link('screen') };
    } else if (!c.ffmpeg.ok) {
      [headline, subline, look] = ['FFmpeg not found', 'Reinstall Goggles Bridge. From the repository, set GOGGLES_FFMPEG to an FFmpeg executable.', 'error'];
      action.disabled = true;
    } else if (!virtual(s) && !display && !active(s)) {
      [headline, subline, look] = [o.display_device ? 'The selected display is disconnected' : 'No display found',
        physicalDisplays(s).length ? 'Choose a connected display in the settings to continue.' : 'Connect a display, then select it in the settings.', 'unplugged'];
      action.disabled = true;
    } else if (virtual(s) && c.virtual_display && (!c.virtual_display.ok || c.virtual_display.installing) && !active(s)) {
      [headline, subline, look] = [c.virtual_display.needs_update ? 'Update the display driver' : GUIDE.virtual_display[0],
        c.virtual_display.problem || GUIDE.virtual_display[1], 'driver'];
      action = driverAction(s, 'virtual_display');
    } else if (fault) {
      headline = fault[0];
      subline = fault[1] || (problem.message || '').split('\n')[0];
      look = failed ? 'error' : cableFault ? 'unplugged' : 'waiting';
      action = failed ? { ...action, label: 'Try again' } : { label: 'Stop', kind: 'stop', run: stop };
    } else if (live) {
      [headline, look] = [`Streaming to ${s.device ? s.device.model : 'the goggles'}`, 'streaming'];
      subline = `${capable(s, 'resolution') ? NAMES.resolution[o.resolution] || NAMES.resolution['1080p'] : NAMES.resolution['1080p']} at ${o.fps} fps and ${bitrate} Mbps.`;
      action = { label: 'Stop', kind: 'stop', run: stop };
    } else if (active(s)) {
      [headline, subline] = BUSY[phase] || ['Starting', ''];
      look = 'waiting';
      action = { label: 'Stop', kind: 'stop', run: stop };
      if (phase === 'stopping') {
        action = { label: 'Stopping…', kind: 'stop', disabled: true };
        if (!virtual(s)) subline = 'Finishing the stream.';
      }
    } else if (c.attached === false) {
      [headline, subline, look] = [GUIDE.cable[0], GUIDE.cable[1], 'unplugged'];
      action.disabled = true;
    } else {
      // Virtual Flight cannot be detected before a stream starts, so say what to do instead of claiming readiness
      [headline, subline, look] = [GUIDE.flight[0], GUIDE.flight[1], 'idle'];
    }
    const stats = live && s.stats ? [`${Math.round(s.stats.fps)} fps`,
      `largest frame ${Math.round(s.stats.frame_bytes_max / 1000)} of ${Math.round(s.frame_limit / 1000)} KB`,
      `USB send ${s.stats.send_ms_p95.toFixed(1)} ms`, ...(s.oversize ? [`${s.oversize} skipped`] : [])].join(' · ') : '';
    const checks = [];
    if (c.driver.needed) checks.push(['DJI driver', c.driver.installing ? 'busy' : c.driver.ok ? 'done' : 'attention',
      c.driver.installing ? 'Installing' : c.driver.ok ? 'Installed' : 'Not installed']);
    if (virtual(s) && c.virtual_display) checks.push(['Separate display', c.virtual_display.installing ? 'busy' : c.virtual_display.ok ? 'done' : 'attention',
      c.virtual_display.installing ? 'Installing' : c.virtual_display.ok ? live ? 'In use' : 'Ready on start' : c.virtual_display.needs_update ? 'Update needed' : 'Driver needed']);
    if (c.screen.needed) checks.push(['Screen recording', c.screen.ok ? 'done' : 'attention', c.screen.ok ? 'Allowed' : 'Not allowed']);
    const d = s.device;
    checks.push([d ? d.model : 'Goggles',
      d && d.tested === false ? 'attention' : c.attached ? 'done' : c.attached === false && c.driver.ok ? 'attention' : 'todo',
      d ? firmware(d) : c.attached ? 'Connected' : c.attached === false ? 'Not connected' : 'Not checked']);
    const notice = d && d.tested === false ? `${untested(d)} Tested firmware: ${d.tested_versions.join(' and ')}.` : '';
    checks.push(['Virtual Flight', live || phase === 'ready' ? 'done' : active(s) && !cableFault ? 'busy' : 'todo',
      live || phase === 'ready' ? 'Open' : active(s) && !cableFault ? 'Waiting' : 'Checked on start']);
    return { display, headline, subline, look, action, stats, checks, notice };
  }

  function setOptions(options) {
    return api.set_options(options).then(result => {
      if (result.error) toast(result.error);
      return refresh();
    });
  }

  function thumbs(node, s) {
    const displays = physicalDisplays(s), chosen = selectedDisplay(s);
    once(`thumbs-${node.id}`, [displays, chosen?.device, chosen?.index], () => {
      node.setAttribute('role', 'radiogroup');
      node.setAttribute('aria-label', 'Display');
      node.replaceChildren(...displays.map(d => {
        const button = el('button', { className: 'display', type: 'button', role: 'radio', text: String(d.index + 1),
          title: `${d.name}: ${d.width} × ${d.height}${d.hz ? `, ${d.hz} Hz` : ''}` });
        button.setAttribute('aria-checked', d === chosen);
        button.setAttribute('aria-label', button.title);
        button.style.aspectRatio = d.width / d.height;
        button.onclick = () => setOptions(d.device ? { display_index: d.index, display_device: d.device } : { display_index: d.index });
        return button;
      }));
    });
  }

  function buildRows(target, rows) {
    for (const row of rows) {
      const label = el('span', { className: 'row-label' }, el('span', { text: row.label }));
      if (row.info) {
        const icon = el('svg', { svg: true, viewBox: '0 0 16 16', 'aria-hidden': 'true' },
          el('circle', { svg: true, cx: 8, cy: 8, r: 6.4 }), el('path', { svg: true, d: 'M8 7.3v3.6M8 4.9v.2' }));
        const tip = el('span', { className: 'tip', role: 'tooltip', id: `tip-${row.key}`, text: row.info });
        const button = el('button', { className: 'info', type: 'button' }, icon);
        button.setAttribute('aria-label', `About ${row.label.toLowerCase()}`);
        button.setAttribute('aria-describedby', tip.id);
        label.append(el('span', { className: 'hint' }, button, tip));
      }
      let control;
      if (row.kind === 'select') {
        control = el('select', { id: `opt-${row.key}` });
        control.setAttribute('aria-label', row.label);
        control.onchange = () => {
          const raw = control.value;
          setOptions({ [row.key]: raw === '' ? null : Number.isNaN(Number(raw)) ? raw : Number(raw) });
        };
      } else if (row.kind === 'switch') {
        const input = el('input', { type: 'checkbox', role: 'switch' });
        input.setAttribute('aria-label', row.label);
        input.onchange = () => setOptions({ [row.key]: input.checked });
        control = el('label', { className: 'switch' }, input, el('span', { className: 'track' }));
      } else if (row.kind === 'segment') {
        control = el('div', { className: 'segmented', role: 'radiogroup' }, el('span', { className: 'thumb' }));
        control.setAttribute('aria-label', row.label);
      } else {
        control = el('div', { className: 'thumbs', id: 'display-picker' });
      }
      controls[row.key] = control;
      const node = el('div', { className: 'row' }, label, control);
      node.dataset.option = row.key;
      if (row.windows) node.dataset.windows = '';
      target.append(node);
    }
  }

  function fill(key, values, labels, current) {
    const node = controls[key];
    once(`select-${key}`, [values, labels], () => {
      node.replaceChildren(...values.map(value => el('option', { value: value ?? '', text: labels[value ?? ''] ?? String(value) })));
    });
    if (document.activeElement !== node) node.value = current ?? '';
  }

  function placeThumb() {
    const chosen = $('input:checked', controls.fps);
    if (!chosen || !chosen.parentElement.offsetWidth) return;
    const thumb = $('.thumb', controls.fps).style;
    thumb.setProperty('--x', `${chosen.parentElement.offsetLeft}px`);
    thumb.setProperty('--w', `${chosen.parentElement.offsetWidth}px`);
  }

  function paint(s, m) {
    const o = s.options;
    document.body.dataset.phase = s.phase;
    $('#headline').textContent = m.headline;
    $('#subline').textContent = m.subline || '';
    $('#stats').textContent = m.stats;
    $('#notice').textContent = m.notice;
    const button = $('#action');
    button.textContent = m.action.label;
    button.dataset.kind = m.action.kind;
    button.disabled = Boolean(m.action.disabled || updating);
    button.onclick = m.action.run;
    const picture = $('.stage .scene');
    picture.dataset.state = m.look;
    picture.setAttribute('aria-label', m.headline);
    $('#version').textContent = `${s.app.name} ${s.app.version}`;
    $('#update').hidden = !s.app.updatable;

    once('checks', m.checks, () => {
      $('#checks').dataset.count = m.checks.length;
      $('#checks').replaceChildren(...m.checks.map(([name, state, note]) => {
        const icon = el('svg', { svg: true, viewBox: '0 0 18 18', 'aria-hidden': 'true' },
          state === 'busy' ? el('path', { svg: true, d: 'M9 1.8A7.2 7.2 0 1 1 1.8 9' }) : el('circle', { svg: true, cx: 9, cy: 9, r: 7.2 }),
          el('path', { svg: true, d: state === 'done' ? 'm5.8 9.3 2.2 2.2 4.2-4.6' : state === 'attention' ? 'M9 5.4v4.2M9 12.3v.2' : '' }));
        const item = el('li', {}, icon, el('b', { text: name }), el('span', { text: note }));
        item.dataset.state = state;
        return item;
      }));
    });

    const locked = active(s) || installing(s);
    $('#options').disabled = locked;
    $('#locked').hidden = !locked;
    $('#locked').textContent = installing(s) ? 'Wait for the driver installation to finish.' : 'To change settings, stop streaming.';
    for (const row of [...BASIC, ...ADVANCED]) controls[row.key].parentElement.hidden = !visibleRow(row, s);
    const displays = physicalDisplays(s);
    const pickDisplay = needsDisplayPicker(s);
    once('display-row', [displays.length, pickDisplay], () => {
      const row = controls.display_index;
      row.className = pickDisplay ? 'thumbs' : 'row-value';
      // the row switches between buttons and plain text, so the buttons must be drawn again next time
      delete drawn['thumbs-display-picker'];
    });
    if (pickDisplay) thumbs(controls.display_index, s);
    else if (m.display) controls.display_index.textContent = `${m.display.width} × ${m.display.height}`;
    else controls.display_index.textContent = 'No display found';
    fill('source', ['display', 'virtual'], NAMES.source, o.source || 'display');
    fill('resolution', ['720p', '1080p'], NAMES.resolution, o.resolution || '1080p');
    $('#tip-bitrate_mbps').textContent = capable(s, 'virtual_display') ? BASIC.find(row => row.key === 'bitrate_mbps').info
      : 'Video data sent each second. Automatic selects the highest bitrate tested at the chosen frame rate.';
    $('#tip-keyframe_seconds').textContent = s.choices.keyframe_seconds.includes(0)
      ? ADVANCED.find(row => row.key === 'keyframe_seconds').info
      : 'Time between complete pictures. The goggles need a complete picture to start or recover the image.';
    once('fps', s.choices.fps, () => {
      controls.fps.append(...s.choices.fps.map(fps => {
        const input = el('input', { type: 'radio', name: 'fps', value: fps });
        input.onchange = () => {
          const allowed = snap.choices.bitrates[fps].allowed.includes(snap.options.bitrate_mbps);
          setOptions(allowed ? { fps } : { fps, bitrate_mbps: null });
        };
        return el('label', {}, input, el('span', { text: String(fps) }));
      }));
    });
    for (const input of $$('input', controls.fps)) input.checked = Number(input.value) === o.fps;
    once('thumb', o.fps, placeThumb);
    const rates = s.choices.bitrates[o.fps];
    fill('bitrate_mbps', [null, ...rates.allowed],
      { '': `Automatic (${rates.auto} Mbps)`, ...Object.fromEntries(rates.allowed.map(r => [r, `${r} Mbps`])) }, o.bitrate_mbps);
    for (const key of ['capture', 'keyframe_seconds', 'h264_profile', 'preset', 'usb_write_size']) {
      fill(key, key === 'capture' ? s.capabilities?.captures || s.choices[key] : s.choices[key], NAMES[key], o[key]);
    }
    for (const key of ['show_cursor', 'adaptive_quant', 'low_latency', 'auto_start']) $('input', controls[key]).checked = Boolean(o[key]);
  }

  function render() {
    const m = model(snap);
    const key = [m.headline, m.action.label].join('|');
    // cross-fade only when the window says something new, not on every poll
    if (painted && painted !== key && !guide.open) morph(() => paint(snap, m));
    else paint(snap, m);
    painted = key;
    renderGuide();
    rest();
  }

  const guideSteps = s => ['welcome', ...(s.checks.driver.needed ? ['driver'] : []), ...(s.checks.screen.needed ? ['screen'] : []), 'cable',
    ...(capable(s, 'virtual_display') ? ['source'] : []), ...(virtual(s) ? ['virtual_display'] : []),
    ...(!virtual(s) && needsDisplayPicker(s) ? ['display'] : []), 'flight', 'done'];

  function go(step) {
    const change = () => { guide.step = step; renderGuide(); };
    if (guide.open && guide.step !== step && document.body.classList.contains('guiding')) morph(change);
    else change();
  }
  function next() {
    const steps = guideSteps(snap);
    go(steps[Math.min(steps.indexOf(guide.step) + 1, steps.length - 1)]);
  }
  function openGuide(step) {
    guide.open = true;
    guide.step = step;
    $('#guide').classList.add('open');
    renderGuide();
    document.body.classList.add('guiding');
  }
  function closeGuide() {
    guide.open = false;
    $('#guide').classList.remove('open');
    document.body.classList.remove('guiding');
    if (!snap.onboarded) api.finish_setup().then(refresh);
  }
  // where a returning user lands in the guide
  function resumeStep(s) {
    if (s.phase === 'streaming') return 'done';
    if (!s.checks.driver.ok) return 'driver';
    if (!s.checks.screen.ok) return 'screen';
    if (virtual(s) && !s.checks.virtual_display?.ok) return 'virtual_display';
    if (!virtual(s) && !selectedDisplay(s) && physicalDisplays(s).length) return 'display';
    return s.checks.attached === false ? 'cable' : 'flight';
  }

  function renderGuide() {
    if (!guide.open) return;
    const s = snap, steps = guideSteps(s);
    const at = Math.max(steps.indexOf(guide.step), 0), step = steps[at];
    guide.step = step;
    $('#guide-title').textContent = GUIDE[step][0];
    $('#guide-text').textContent = GUIDE[step][1];
    once('dots', steps.length, () => $('#dots').replaceChildren(...steps.map(() => el('i'))));
    $$('#dots i').forEach((dot, i) => { dot.className = i === at ? 'current' : i < at ? 'past' : ''; });
    const picker = $('#guide-picker');
    picker.hidden = step !== 'display';
    thumbs(picker, s);
    $('#guide-source-row').hidden = step !== 'source';
    const source = $('#guide-source');
    source.disabled = active(s) || installing(s);
    if (document.activeElement !== source) source.value = s.options.source || 'display';
    $('#guide-help').hidden = step !== 'driver';

    // a detected step shows a check and waits for the user to continue
    let label = 'Continue', kind = 'start', run = next, disabled = false, status = '', state = '';
    let look = { welcome: 'welcome', driver: 'driver', virtual_display: 'driver', screen: 'driver', cable: 'unplugged', source: 'idle', display: 'idle', flight: 'idle', done: 'streaming' }[step];
    if (step === 'welcome') {
      label = 'Set up';
    } else if (step === 'driver' || step === 'virtual_display') {
      const check = s.checks[step];
      if (check?.ok && !check.installing) [status, state, look] = ['Driver installed', 'done', 'unplugged'];
      else {
        const action = driverAction(s, step);
        ({ label, run, disabled = false } = action);
        [status, state] = check.installing ? ['Complete the Windows installation prompt.', 'waiting']
          : check.problem ? [check.problem, 'bad'] : [check.needs_update ? 'A driver update is needed.' : 'Driver not installed.', ''];
      }
    } else if (step === 'screen') {
      if (s.checks.screen.ok) [status, state, look] = ['Screen recording allowed', 'done', 'unplugged'];
      else [label, run, status, state] = ['Open Settings', () => api.open_link('screen'), 'Waiting for permission', 'waiting'];
    } else if (step === 'cable') {
      const d = s.device;
      if (s.checks.attached === true && d && d.tested === false) [status, state, look] = [`${d.model} connected. ${untested(d)}`, 'warn', 'idle'];
      else if (s.checks.attached === true) [status, state, look] = [d ? `${d.model} connected. ${firmware(d)}.` : 'Goggles connected', 'done', 'idle'];
      else if (s.checks.attached === null) status = 'This computer cannot check the USB port.';
      else [disabled, status, state] = [true, 'Waiting for the goggles', 'waiting'];
    } else if (step === 'flight') {
      if (s.phase === 'streaming') return go('done');
      if (s.phase === 'error') {
        const fault = PROBLEMS[s.problem.code] || PROBLEMS.other;
        [label, run, state, look] = ['Try again', start, 'bad', 'error'];
        status = `${fault[0]}. ${fault[1] || (s.problem.message || '').split('\n')[0]}`;
      } else if (active(s)) {
        [label, kind, run, state, look] = ['Cancel', 'stop', stop, 'waiting', 'waiting'];
        status = s.phase === 'waiting' ? (PROBLEMS[s.problem.code] || PROBLEMS.other)[0] : (BUSY[s.phase] || ['Starting'])[0];
        if (s.phase === 'stopping') [label, disabled] = ['Stopping…', true];
      } else {
        [label, run] = ['Start streaming', start];
      }
    } else if (step === 'done') {
      [label, run] = ['Done', closeGuide];
    }
    $('.guide .scene').dataset.state = look;
    const button = $('#guide-action');
    button.textContent = label;
    button.dataset.kind = kind;
    button.disabled = disabled;
    button.onclick = run;
    $('#guide-status').dataset.state = state;
    const line = $('#guide-status-text');
    if (line.textContent !== status) {
      line.textContent = status;
      line.classList.remove('fresh');
      void line.offsetWidth;
      line.classList.add('fresh');
    }
    const skip = $('#guide-skip');
    skip.textContent = s.onboarded ? 'Close' : 'Skip';
    skip.style.visibility = step === 'done' ? 'hidden' : '';
  }

  // stop drawing when nobody is looking, so a running stream keeps the GPU to itself
  function rest() {
    const idle = document.hidden || (snap && snap.phase === 'streaming' && !document.hasFocus());
    document.documentElement.classList.toggle('asleep', Boolean(idle));
  }

  // the footer button checks for a release, then installs the one it found
  async function checkUpdate(asked) {
    const button = $('#update');
    const found = await api.check_update();
    if (found.version) {
      button.textContent = `Update to ${found.version}`;
      button.onclick = async () => {
        button.disabled = updating = true;
        button.textContent = `Downloading ${found.version}`;
        const result = await api.install_update();
        if (!result.error) return;
        toast(result.error);
        button.disabled = updating = false;
        button.textContent = `Update to ${found.version}`;
      };
    } else if (asked) toast(found.error || `${snap.app.name} is up to date`);
  }

  async function refresh() {
    snap = await api.snapshot();
    render();
  }

  function loop() {
    const again = () => setTimeout(loop, snap && active(snap) ? 1000 : 500);
    if (document.hidden) again();
    else refresh().catch(error => console.error(error)).finally(again);
  }

  async function boot(backend) {
    api = backend;
    for (const slot of $$('[data-scene]')) slot.append(scene());
    buildRows($('#basic'), BASIC);
    buildRows($('#advanced'), ADVANCED);
    for (const node of $$('[data-link]')) node.onclick = () => api.open_link(node.dataset.link);
    $('#diagnostics').onclick = () => api.diagnostics().then(() => toast('Diagnostics copied'));
    $('#open-guide').onclick = () => openGuide(resumeStep(snap));
    $('#guide-skip').onclick = closeGuide;
    $('#guide-source').onchange = event => setOptions({ source: event.target.value });
    addEventListener('keydown', event => {
      if (!guide.open) return;
      if (event.key === 'Escape') closeGuide();
      if (event.key === 'Enter' && document.activeElement === document.body) $('#guide-action').click();
    });
    addEventListener('resize', placeThumb);
    for (const name of ['visibilitychange', 'focus', 'blur']) addEventListener(name, rest);
    $('#guide').hidden = false;
    $('#update').onclick = () => checkUpdate(true);
    await refresh();
    if (snap.app.updatable) checkUpdate(false);
    if (!snap.onboarded || params.has('step')) openGuide(params.get('step') || 'welcome');
    requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.add('ready')));
    loop();
  }

  // opened as a plain file, or with ?demo, the window runs on a simulated backend
  if (location.protocol === 'file:' || params.has('demo')) {
    const script = el('script', { src: 'demo.js' });
    script.onload = () => boot(window.demoBackend);
    document.head.append(script);
  } else if (window.pywebview && window.pywebview.api) {
    boot(window.pywebview.api);
  } else {
    window.addEventListener('pywebviewready', () => boot(window.pywebview.api), { once: true });
  }
})();
