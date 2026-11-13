const caseSelect = document.querySelector('#preview-case');
const status = document.querySelector('#player-status');
const identity = document.querySelector('#player-identity');
const fallback = document.querySelector('#fallback');
let previews = [];
let context;
let buffers = [];
let sources = [];
let startTime = 0;
let offset = 0;
let playing = false;
let active = 0;
let reveal = false;

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
    const tracks = preview.tracks.filter(track => typeof track.path === 'string' && !track.path.includes('..'));
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
  stopSources();
  const item = previews.find(entry => entry.case_id === caseSelect.value);
  if (!item) return;
  const tracks = item.tracks.slice(0, 2);
  try {
    context ||= new AudioContext();
    buffers = await Promise.all(tracks.map(async track => {
      const url = new URL(track.path, location.href);
      if (url.origin !== location.origin || url.pathname.includes('..')) throw new Error('Unsafe preview path');
      const response = await fetch(url, { credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Preview unavailable: ${response.status}`);
      return context.decodeAudioData(await response.arrayBuffer());
    }));
    offset = 0;
    active = 0;
    fallback.hidden = true;
    status.textContent = 'Both tracks decoded; synchronized switching is available.';
    identity.textContent = reveal ? (item.identity || item.case_id) : 'Identity hidden';
  } catch (error) {
    buffers = [];
    fallback.replaceChildren();
    for (const track of tracks) {
      const audio = document.createElement('audio');
      audio.controls = true;
      audio.src = new URL(track.path, location.href).href;
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
  source.buffer = buffers[active];
  source.connect(context.destination);
  sources = [source];
  startTime = context.currentTime;
  source.start(0, offset % buffers[active].duration);
  playing = true;
  source.onended = () => { if (playing) { offset = 0; playing = false; } };
  status.textContent = `Playing track ${active === 0 ? 'A' : 'B'}.`;
}
function pause() {
  stopSources();
  status.textContent = 'Paused.';
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
