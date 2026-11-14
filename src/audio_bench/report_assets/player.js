const caseSelect = document.querySelector('#preview-case');
const status = document.querySelector('#player-status');
const identity = document.querySelector('#player-identity');
const fallback = document.querySelector('#fallback');
const seek = document.querySelector('#seek');
const position = document.querySelector('#position');
let previews = [];
let context;
let buffers = [];
let sources = [];
let startTime = 0;
let offset = 0;
let playing = false;
let active = 0;
let reveal = false;
let playbackToken = 0;
let selectionToken = 0;
const MAX_DECODED_BYTES = 20 * 1024 * 1024;

function safePreviewUrl(path) {
  if (typeof path !== 'string' || path.includes('%') || path.includes('\\') || path.startsWith('/')) {
    throw new Error('Unsafe preview path');
  }
  const parts = path.split('/');
  if (parts[0] !== 'media' || parts.some(part => !part || part === '.' || part === '..')) {
    throw new Error('Unsafe preview path');
  }
  const url = new URL(path, location.href);
  const base = location.pathname.slice(0, location.pathname.lastIndexOf('/') + 1);
  if (url.origin !== location.origin || !url.pathname.startsWith(`${base}media/`)) {
    throw new Error('Preview must remain beneath this report origin and path');
  }
  return url;
}

async function loadIndex() {
  const response = await fetch('data/index.json', { credentials: 'same-origin' });
  if (!response.ok) throw new Error('Could not load report index');
  const index = await response.json();
  // Gallery is enabled only when an explicit same-origin media index exists.
  const mediaResponse = await fetch('media/index.json', { credentials: 'same-origin' });
  if (!mediaResponse.ok) {
    status.textContent = 'No authorized preview media is bundled.';
    return;
  }
  previews = await mediaResponse.json();
  let budget = 0;
  for (const preview of previews) {
    if (!preview || typeof preview.case_id !== 'string' || !Array.isArray(preview.tracks)) continue;
     const tracks = preview.tracks.filter(track => {
       try { safePreviewUrl(track.path); return true; } catch { return false; }
     });
    if (tracks.length < 2) continue;
    const optionNode = document.createElement('option');
    optionNode.value = preview.case_id;
    optionNode.textContent = preview.case_id;
    caseSelect.append(optionNode);
    budget += tracks.slice(0, 2).reduce((sum, track) => sum + Number(track.bytes || 0), 0);
    if (budget > Number(index.caps.preview_preload_bytes)) {
      status.textContent = 'Preview preload cap reached; further clips load on demand.';
      break;
    }
  }
  caseSelect.addEventListener('change', selectCase);
}
async function selectCase() {
  const selection = ++selectionToken;
  stopSources();
  const item = previews.find(entry => entry.case_id === caseSelect.value);
  if (!item) return;
  const tracks = item.tracks.slice(0, 2);
  try {
    context ||= new AudioContext();
    const expectedDecodedBytes = tracks.reduce((sum, track) => {
      const frames = Number(track.frames);
      const channels = Number(track.channels);
      if (!Number.isSafeInteger(frames) || frames < 0 || !Number.isSafeInteger(channels) ||
          channels < 1 || channels > 2) throw new Error('Invalid preview audio dimensions');
      return sum + frames * channels * 4;
    }, 0);
    if (expectedDecodedBytes > MAX_DECODED_BYTES) throw new Error('Decoded preview memory cap exceeded');
    const loaded = await Promise.all(tracks.map(async track => {
      const url = safePreviewUrl(track.path);
      const response = await fetch(url, { credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Preview unavailable: ${response.status}`);
      const declared = Number(track.bytes);
      const headerLength = Number(response.headers.get('content-length'));
      if (!Number.isSafeInteger(declared) || declared < 1 || declared > MAX_DECODED_BYTES ||
          (Number.isFinite(headerLength) && headerLength !== declared)) throw new Error('Preview byte cap or length mismatch');
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength !== declared) throw new Error('Preview byte length mismatch');
      const decoded = await context.decodeAudioData(bytes);
      if (decoded.length !== Number(track.frames) || decoded.numberOfChannels !== Number(track.channels)) {
        throw new Error('Decoded preview dimensions differ from the authorized index');
      }
      return decoded;
    }));
    if (selection !== selectionToken) return;
    buffers = loaded;
    if (buffers.reduce((sum, buffer) => sum + buffer.length * buffer.numberOfChannels * 4, 0) > MAX_DECODED_BYTES) {
      throw new Error('Decoded preview memory cap exceeded');
    }
    if (Math.abs(buffers[0].duration - buffers[1].duration) > 1 / buffers[0].sampleRate) {
      throw new Error('A/B tracks do not have equal duration');
    }
    offset = 0;
    active = 0;
    seek.disabled = false;
    seek.max = String(buffers[active].duration);
    seek.value = '0';
    position.value = '0.00 s';
    fallback.hidden = true;
    status.textContent = 'Both tracks decoded; synchronized switching is available.';
    identity.textContent = reveal ? (item.identity || item.case_id) : 'Identity hidden';
  } catch (error) {
    if (selection !== selectionToken) return;
    buffers = [];
    fallback.replaceChildren();
    for (const track of tracks) {
      const audio = document.createElement('audio');
      audio.controls = true;
      try {
        audio.src = safePreviewUrl(track.path).href;
      } catch {
        continue;
      }
      audio.preload = 'none';
      const label = document.createElement('p');
      label.textContent = track.label || 'Audio track';
      fallback.append(label, audio);
    }
    fallback.hidden = false;
    status.textContent = `Synchronized decoder unavailable; individual players only. ${error.message}`;
  }
}
function stopSources() {
  if (playing && context) offset += Math.max(0, context.currentTime - startTime);
  playbackToken += 1;
  for (const source of sources) {
    try { source.stop(); } catch { /* already stopped */ }
  }
  sources = [];
  playing = false;
}
function play() {
  if (!buffers.length || !context) return;
  stopSources();
  const source = context.createBufferSource();
  const token = ++playbackToken;
  source.buffer = buffers[active];
  source.connect(context.destination);
  sources = [source];
  startTime = context.currentTime;
  offset %= buffers[active].duration;
  source.start(0, offset);
  playing = true;
  source.onended = () => {
    if (token === playbackToken && playing) {
      offset = 0;
      playing = false;
      seek.value = '0';
      position.value = '0.00 s';
    }
  };
  const updatePosition = () => {
    if (token !== playbackToken || !playing) return;
    const current = Math.min(buffers[active].duration, offset + context.currentTime - startTime);
    seek.value = String(current);
    position.value = `${current.toFixed(2)} s`;
    requestAnimationFrame(updatePosition);
  };
  requestAnimationFrame(updatePosition);
  status.textContent = `Playing track ${active === 0 ? 'A' : 'B'}.`;
}
function pause() {
  stopSources();
  status.textContent = 'Paused.';
}
function seekTo(value) {
  if (!buffers.length) return;
  const wasPlaying = playing;
  stopSources();
  offset = Math.max(0, Math.min(Number(value), buffers[active].duration));
  seek.value = String(offset);
  position.value = `${offset.toFixed(2)} s`;
  if (wasPlaying) play();
}
function switchTrack() {
  if (buffers.length < 2) return;
  const wasPlaying = playing;
  stopSources();
  active = 1 - active;
  status.textContent = `Switched to track ${active === 0 ? 'A' : 'B'} at the same sample position.`;
  if (wasPlaying) play();
}
document.querySelector('#play').addEventListener('click', play);
document.querySelector('#pause').addEventListener('click', pause);
document.querySelector('#switch').addEventListener('click', switchTrack);
seek.addEventListener('input', () => seekTo(seek.value));
document.querySelector('#reveal').addEventListener('click', () => {
  reveal = !reveal;
  identity.textContent = reveal ? (previews.find(item => item.case_id === caseSelect.value)?.identity || caseSelect.value) : 'Identity hidden';
});
document.addEventListener('keydown', event => {
  if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(document.activeElement?.tagName)) return;
  if (event.code === 'Space') { event.preventDefault(); playing ? pause() : play(); }
  if (event.key.toLowerCase() === 'a' || event.key.toLowerCase() === 'b') switchTrack();
  if (event.key.toLowerCase() === 'i') document.querySelector('#reveal').click();
});
loadIndex().catch(error => { status.textContent = error.message; });
