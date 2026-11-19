const resultsHost = document.querySelector('#results');
const status = document.querySelector('#status');
const comparisonNote = document.querySelector('#comparison-note');
const metricToggle = document.querySelector('#metric-toggle');
const search = document.querySelector('#search');
const runnerFilter = document.querySelector('#runner-filter');
const suiteFilter = document.querySelector('#suite-filter');
const clearButton = document.querySelector('#clear-filters');
const categoryButtons = [...document.querySelectorAll('[data-category]')];
const categories = {
  'speech-enhancement': 'Speech enhancement',
  'real-time-processing': 'Real-time processing',
};
const suites = {
  'voicebank-demand-paired-v1': 'VoiceBank+DEMAND',
  'realtime-throughput-v1': 'Paced real-time load',
  'synthetic-smoke-v1': 'Synthetic smoke check',
};
const metricInfo = {
  si_sdr_improvement_db: ['SI-SDR improvement', 'Higher is better', 'desc'],
  si_sdr_db: ['SI-SDR', 'Higher is better', 'desc'],
  stoi: ['STOI', 'Higher is better', 'desc'],
  estoi: ['ESTOI', 'Higher is better', 'desc'],
  latency_ms: ['CPU time per frame', 'Lower uses less CPU', 'asc'],
  max_tested_streams_at_latency_target: ['Streams at target', 'Higher is better', 'desc'],
  p99_completion_lateness_ms: ['p99 lateness', 'Lower is better', 'asc'],
  cpu_occupancy_cores: ['CPU use', '', 'asc'],
  cpu_seconds_per_audio_second: ['CPU seconds per audio second', '', 'asc'],
  throughput_audio_seconds_per_wall_second: ['Throughput', 'Higher is better', 'desc'],
  peak_worker_rss_bytes: ['Peak worker memory', '', 'asc'],
  sum_worker_peak_rss_bytes: ['Sum of worker memory peaks', '', 'asc'],
};
const highlights = {
  'voicebank-demand-paired-v1': ['si_sdr_improvement_db', 'estoi', 'latency_ms'],
  'realtime-throughput-v1': ['max_tested_streams_at_latency_target', 'p99_completion_lateness_ms', 'throughput_audio_seconds_per_wall_second'],
  'synthetic-smoke-v1': ['latency_ms', 'throughput_audio_seconds_per_wall_second', 'peak_worker_rss_bytes'],
};
const count = new Intl.NumberFormat();
const precise = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 });
let records = [];
let category = '';
let showAllMetrics = false;
let sort = { key: 'display_name', direction: 'asc' };

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value ?? '—';
  if (className) node.className = className;
  return node;
}

function addLink(parent, label, value) {
  if (typeof value !== 'string') return;
  let url;
  try { url = new URL(value); } catch { return; }
  if (url.protocol !== 'https:') return;
  const link = text('a', label);
  link.href = url.href;
  link.rel = 'noreferrer';
  parent.append(link);
}

function suiteLabel(id) { return Object.hasOwn(suites, id) ? suites[id] : id; }
function categoryLabel(id) { return Object.hasOwn(categories, id) ? categories[id] : id; }
function runnerLabel(row) { return row.runner_mode === 'submitter-owned' ? 'Submitter' : 'Audio Bench'; }
function metricLabel(metric) {
  const label = (metric.label || metric.metric_id).replaceAll('_', ' ');
  return metricInfo[metric.metric_id]?.[0] || label.charAt(0).toUpperCase() + label.slice(1);
}

function preferredMetrics(suite, measurements) {
  const ids = Object.hasOwn(highlights, suite) ? highlights[suite] : [];
  const preferred = ids.map(id => measurements.get(id)).filter(Boolean);
  return preferred.length ? preferred : [...measurements.values()].slice(0, 3);
}

function sortValue(row, key) {
  if (key.startsWith('metric:')) return row.measurements.get(key.slice(7))?.median ?? null;
  if (key === 'suite_id') return suiteLabel(row.suite_id);
  if (key === 'runner_mode') return runnerLabel(row);
  return row[key] || '';
}

function compareRows(a, b) {
  const left = sortValue(a, sort.key);
  const right = sortValue(b, sort.key);
  if (left == null || right == null) return Number(left == null) - Number(right == null);
  const order = typeof left === 'number' && typeof right === 'number'
    ? left - right : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' });
  return sort.direction === 'asc' ? order : -order;
}

function fillMeasurement(parent, metric) {
  parent.append(text('strong', metric.display_value || metric.raw_display_value || String(metric.median ?? '—')));
  if (metric.normalized_display_value) {
    parent.append(text('span', `Normalized estimate ${metric.normalized_display_value}`, 'table-subline'));
  }
  if (metric.raw_display_value && metric.raw_display_value !== metric.display_value && metric.display_value) {
    parent.append(text('span', `Raw ${metric.raw_display_value}`, 'table-subline'));
  }
}

function measurementList(metrics, detailed = false) {
  const list = document.createElement('dl');
  list.className = 'measurement-list';
  for (const metric of metrics) {
    const item = document.createElement('div');
    const label = text('dt', metricLabel(metric));
    const value = document.createElement('dd');
    fillMeasurement(value, metric);
    if (detailed && Array.isArray(metric.median_interval_95)) {
      const [low, high] = metric.median_interval_95.map(number => precise.format(number));
      value.append(text('span', `95% interval ${low} to ${high}`, 'table-subline'));
    }
    item.append(label, value);
    list.append(item);
  }
  return list;
}

function pipelineCell(row, openDetails) {
  const cell = document.createElement('td');
  cell.className = 'pipeline';
  cell.append(text('strong', row.display_name), text('span', row.provider_id, 'table-subline'));
  const details = document.createElement('details');
  details.open = openDetails.has(row.result_id);
  const summary = text('summary', 'Run details');
  summary.setAttribute('aria-label', `Run details for ${row.display_name}`);
  details.append(summary);
  const info = document.createElement('div');
  info.className = 'table-details';
  info.append(text('span', row.result_status || 'Published'));
  info.append(text('span', `Dataset · ${row.dataset_label || row.dataset_id || '—'}`));
  if (row.case_count) info.append(text('span', `Cases · ${count.format(row.case_count)}`));
  if (row.source?.visibility === 'private') {
    info.append(text('span', `Private source identity · ${row.source.repository_identity_sha256 || '—'}`));
  }
  if (row.source?.revision) info.append(text('span', `Source commit · ${row.source.revision}`));
  if (row.model_digest) info.append(text('span', `Model digest · ${row.model_digest}`));
  for (const [key, value] of Object.entries(row.evidence || {})) {
    if (value && (key.endsWith('_digest') || key.endsWith('_fingerprint') || key.endsWith('_semantics') || key === 'latency_budget_ms')) {
      info.append(text('span', `${key.replaceAll('_', ' ')} · ${value}`));
    }
  }
  if (row.runner_mode === 'submitter-owned') info.append(text('strong', 'Not independently verified'));
  if (row.measurements.size) {
    info.append(text('strong', 'All measurements'), measurementList(row.measurements.values(), true));
  }
  addLink(info, 'View source ↗', row.source?.url);
  addLink(info, 'Scoring protocol ↗', row.protocol_url);
  addLink(info, 'Dataset source ↗', row.dataset_source_url);
  addLink(info, 'Evidence record ↗', row.result_url);
  details.append(info);
  cell.append(details);
  return cell;
}

function addColumn(header, column) {
  const [key, label, note, preferred = 'asc'] = column;
  const th = document.createElement('th');
  th.scope = 'col';
  th.setAttribute('role', 'columnheader');
  if (!key) {
    th.textContent = label;
    header.append(th);
    return;
  }
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'sort-button';
  button.dataset.sort = key;
  const active = sort.key === key;
  const caption = text('div', label);
  if (note) caption.append(text('small', note));
  const arrow = text('span', active ? (sort.direction === 'asc' ? '↑' : '↓') : '↕');
  arrow.setAttribute('aria-hidden', 'true');
  button.append(caption, arrow);
  if (active) th.setAttribute('aria-sort', sort.direction === 'asc' ? 'ascending' : 'descending');
  button.addEventListener('click', () => {
    const direction = active ? (sort.direction === 'asc' ? 'desc' : 'asc') : preferred;
    sort = { key, direction };
    const scroll = resultsHost.firstElementChild.scrollLeft;
    render();
    resultsHost.firstElementChild.scrollLeft = scroll;
    [...resultsHost.querySelectorAll('[data-sort]')].find(item => item.dataset.sort === key)?.focus();
  });
  th.append(button);
  header.append(th);
}

function renderTable(visible, columns, measurements, activeSuite, openDetails) {
  const region = document.createElement('div');
  region.className = 'table-wrap';
  region.tabIndex = 0;
  region.setAttribute('role', 'region');
  region.setAttribute('aria-label', 'Benchmark comparison table');
  const table = document.createElement('table');
  table.className = 'results-table';
  table.setAttribute('role', 'table');
  table.setAttribute('aria-label', activeSuite ? `${suiteLabel(activeSuite)} results` : 'Results across suites');
  const head = table.createTHead().insertRow();
  head.setAttribute('role', 'row');
  for (const column of columns) addColumn(head, column);
  const body = table.createTBody();
  for (const row of visible) {
    const tr = body.insertRow();
    tr.setAttribute('role', 'row');
    tr.dataset.resultId = row.result_id;
    const suite = document.createElement('td');
    suite.className = 'suite-cell';
    suite.append(text('strong', suiteLabel(row.suite_id)), text('span', categoryLabel(row.category_id), 'table-subline'));
    const runner = text('td', '');
    runner.dataset.label = 'Run by';
    const external = row.runner_mode === 'submitter-owned';
    runner.append(text('span', runnerLabel(row), `tag ${external ? 'tag-owner' : 'tag-verified'}`));
    if (external) runner.append(text('span', 'Not independently verified', 'table-subline'));
    tr.append(pipelineCell(row, openDetails), suite, runner);
    if (!activeSuite) {
      const cell = tr.insertCell();
      cell.className = 'metric-cell';
      cell.classList.add('metric-summary');
      const metrics = preferredMetrics(row.suite_id, row.measurements);
      cell.append(metrics.length ? measurementList(metrics) : text('span', '—'));
    }
    for (const column of measurements) {
      const cell = tr.insertCell();
      cell.className = 'metric-cell';
      cell.dataset.label = metricLabel(column);
      const metric = row.measurements.get(column.metric_id);
      if (metric) fillMeasurement(cell, metric);
      else cell.textContent = '—';
    }
    for (const cell of tr.cells) cell.setAttribute('role', 'cell');
  }
  region.append(table);
  resultsHost.append(region);
}

function renderEmpty() {
  const empty = document.createElement('div');
  empty.className = 'empty';
  if (records.length) {
    const reset = text('button', 'Clear filters', 'text-button');
    reset.type = 'button';
    reset.addEventListener('click', resetFilters);
    empty.append(text('h3', 'No matching results'), text('p', 'Try a shorter search or clear your filters.'), reset);
  } else {
    empty.append(text('h3', 'No published results yet'), text('p', 'The first accepted run will appear here with its measurements and run evidence.'));
    addLink(empty, 'How to submit a pipeline ↗', 'https://github.com/armaudia/audio-bench/blob/main/docs/SUBMISSIONS.md');
  }
  resultsHost.append(empty);
}

function render() {
  const openDetails = new Set([...resultsHost.querySelectorAll('details[open]')]
    .map(details => details.closest('tr').dataset.resultId));
  const term = search.value.trim().toLowerCase();
  const runner = runnerFilter.value;
  const suite = suiteFilter.value;
  const visible = records.filter(row => (!term || row.searchText.includes(term)) &&
    (!category || row.category_id === category) && (!runner || row.runner_mode === runner) &&
    (!suite || row.suite_id === suite));
  const visibleSuites = new Set(visible.map(row => row.suite_id));
  const activeSuite = visibleSuites.size === 1 ? visible[0].suite_id : null;
  const measurements = new Map();
  if (activeSuite) {
    for (const row of visible) {
      for (const [id, metric] of row.measurements) measurements.set(id, metric);
    }
  }
  const featured = preferredMetrics(activeSuite, measurements);
  const metricColumns = showAllMetrics ? [...measurements.values()] : featured;
  metricToggle.hidden = measurements.size <= featured.length;
  metricToggle.textContent = showAllMetrics ? 'Show key metrics' : `Show all ${measurements.size} metrics`;
  const columns = [
    ['display_name', 'Pipeline'],
    ['suite_id', 'Benchmark suite'],
    ['runner_mode', 'Run by'],
    ...metricColumns.map(metric => {
      const spec = metricInfo[metric.metric_id];
      return [`metric:${metric.metric_id}`, metricLabel(metric), spec?.[1], spec?.[2]];
    }),
  ];
  if (!activeSuite) columns.push([null, 'Key measurements']);
  if (!columns.some(([key]) => key === sort.key)) sort = { key: 'display_name', direction: 'asc' };
  resultsHost.replaceChildren();
  clearButton.disabled = !term && !category && !runner && !suite;
  status.textContent = `${count.format(visible.length)} of ${count.format(records.length)} runs`;
  comparisonNote.hidden = !visible.length;
  comparisonNote.textContent = activeSuite
    ? (activeSuite === 'synthetic-smoke-v1' ? 'Synthetic integration check' : 'Compare runs on similar hardware.')
    : 'Select one suite to sort by its metrics.';
  if (visible.length) renderTable(visible.sort(compareRows), columns, metricColumns, activeSuite, openDetails);
  else renderEmpty();
}

function selectCategory(value) {
  category = value;
  for (const button of categoryButtons) button.setAttribute('aria-pressed', String(button.dataset.category === category));
  const selectedSuite = suiteFilter.value;
  const available = [...new Set(records.filter(row => !category || row.category_id === category).map(row => row.suite_id))]
    .sort((a, b) => suiteLabel(a).localeCompare(suiteLabel(b)));
  suiteFilter.replaceChildren(new Option('All suites', ''), ...available.map(id => new Option(suiteLabel(id), id)));
  if (available.includes(selectedSuite)) suiteFilter.value = selectedSuite;
  suiteFilter.disabled = !available.length;
  render();
}

function resetFilters() {
  search.value = ''; runnerFilter.value = ''; suiteFilter.value = '';
  showAllMetrics = false;
  selectCategory('');
  search.focus();
}

async function main() {
  const url = `data/results.json?refresh=${Date.now()}`;
  const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not load results (HTTP ${response.status}).`);
  const data = await response.json();
  if (data.schema_id !== 'audio-bench/site-results/0.1' || !Array.isArray(data.results)) {
    throw new Error('Results index has an unsupported format.');
  }
  records = data.results.map(row => {
    const categoryId = row.category_id ||
      (row.task?.toLowerCase().includes('filter') || row.provider_id === 'dsp.highpass80.v0'
        ? 'real-time-processing' : 'speech-enhancement');
    return {
      ...row,
      category_id: categoryId,
      searchText: [row.display_name, row.provider_id, row.source?.repository, row.task,
        row.dataset_label, row.dataset_id, suiteLabel(row.suite_id), categoryLabel(categoryId)].join(' ').toLowerCase(),
      measurements: new Map((row.metrics || []).map(metric => [metric.metric_id, metric])),
    };
  });
  document.querySelector('#result-count').textContent = count.format(records.length);
  document.querySelector('#pipeline-count').textContent = count.format(new Set(records.map(row => row.submission_id)).size);
  document.querySelector('#suite-count').textContent = count.format(new Set(records.map(row => row.suite_id)).size);
  document.querySelector('.download').href = url;
  for (const control of [search, runnerFilter, suiteFilter]) control.addEventListener('input', render);
  for (const button of categoryButtons) button.addEventListener('click', () => selectCategory(button.dataset.category));
  clearButton.addEventListener('click', resetFilters);
  metricToggle.addEventListener('click', () => {
    showAllMetrics = !showAllMetrics;
    render();
  });
  document.querySelector('#filter-form').addEventListener('submit', event => event.preventDefault());
  selectCategory('');
}
main().catch(error => {
  status.classList.add('error');
  status.textContent = `${error.message} Reload the page to try again.`;
});
