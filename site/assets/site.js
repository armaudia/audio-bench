const resultsHost = document.querySelector('#results');
const status = document.querySelector('#status');
const search = document.querySelector('#search');
const categoryFilter = document.querySelector('#category-filter');
const runnerFilter = document.querySelector('#runner-filter');
const suiteFilter = document.querySelector('#suite-filter');
const categories = {
  'speech-enhancement': { label: 'Speech enhancement', description: 'Audio quality and runtime performance' },
  'real-time-processing': { label: 'Real-time processing', description: 'Runtime performance; no quality score' },
};
let records = [];
let sort = { key: 'display_name', direction: 'asc' };

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value ?? '—';
  if (className) node.className = className;
  return node;
}

function safeHttpUrl(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
}

function metricMap(row) { return new Map((row.metrics || []).map(metric => [metric.metric_id, metric])); }
function metricValue(row, id) {
  const metric = metricMap(row).get(id);
  return metric && Number.isFinite(metric.median) ? metric.median : null;
}
function labelCategory(row) { return categories[row.category_id]?.label || row.category_id || 'Uncategorized'; }
function sortValue(row, key) {
  if (key.startsWith('metric:')) return metricValue(row, key.slice(7));
  if (key === 'category_id') return labelCategory(row);
  if (key === 'runner_mode') return row.runner_mode === 'submitter-owned' ? 'Submitter-owned' : 'Audio-bench';
  return row[key] || '';
}
function compareRows(a, b) {
  const av = sortValue(a, sort.key), bv = sortValue(b, sort.key);
  if (av === null || av === undefined || av === '') return bv === null || bv === undefined || bv === '' ? 0 : 1;
  if (bv === null || bv === undefined || bv === '') return -1;
  const result = typeof av === 'number' && typeof bv === 'number'
    ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
  return sort.direction === 'asc' ? result : -result;
}

function addLink(parent, label, value) {
  const url = safeHttpUrl(value);
  if (!url) return;
  const link = document.createElement('a');
  link.href = url; link.rel = 'noreferrer'; link.textContent = label;
  parent.append(link);
}

function pipelineCell(row) {
  const cell = document.createElement('td');
  cell.append(text('strong', row.display_name));
  cell.append(text('span', row.provider_id, 'table-subline'));
  const details = document.createElement('details');
  details.append(text('summary', 'Provenance'));
  const info = document.createElement('div'); info.className = 'table-details';
  info.append(text('span', `Status: ${row.result_status || 'published'}`));
  info.append(text('span', `Dataset: ${row.dataset_label || row.dataset_id || '—'}`));
  if (row.case_count) info.append(text('span', `${row.case_count} paired utterances`));
  if (row.source?.visibility === 'private') {
    info.append(text('span', `Private source identity: ${row.source.repository_identity_sha256 || '—'}`));
    info.append(text('span', `Source commit: ${row.source.revision || '—'}`));
  } else {
    info.append(text('span', `Source: ${row.source?.revision || '—'}`));
    addLink(info, 'View source →', row.source?.url);
  }
  info.append(text('span', `Model: ${row.model_digest || 'not applicable'}`));
  for (const [key, value] of Object.entries(row.evidence || {})) {
    if (value && (key.endsWith('_digest') || key === 'runner_fingerprint' || key === 'latency_budget_ms')) {
      info.append(text('span', `${key.replaceAll('_', ' ')}: ${value}`));
    }
  }
  if (row.runner_mode === 'submitter-owned') info.append(text('span', 'Not independently verified', 'warning'));
  addLink(info, 'Scoring protocol →', row.protocol_url);
  addLink(info, 'Dataset source →', row.dataset_source_url);
  addLink(info, 'Evidence record →', row.result_url);
  details.append(info); cell.append(details);
  return cell;
}

function render() {
  const term = search.value.trim().toLowerCase();
  const category = categoryFilter.value;
  const runner = runnerFilter.value;
  const suite = suiteFilter.value;
  const visible = records.filter(row => {
    const content = [row.display_name, row.provider_id, row.source?.repository, row.task].join(' ').toLowerCase();
    return (!term || content.includes(term)) && (!category || row.category_id === category)
      && (!runner || row.runner_mode === runner) && (!suite || row.suite_id === suite);
  }).sort(compareRows);
  resultsHost.replaceChildren();
  if (!visible.length) {
    resultsHost.append(text('p', records.length ? 'No results match those filters.' : 'No validated benchmark run has been published yet.', 'empty'));
    status.textContent = records.length ? `0 of ${records.length} results` : 'Results are empty';
    return;
  }
  status.textContent = `Showing ${visible.length} of ${records.length} results`;
  const metricIds = [...new Set(visible.flatMap(row => (row.metrics || []).map(metric => metric.metric_id)))];
  const metricLabels = new Map();
  for (const row of visible) for (const metric of row.metrics || []) metricLabels.set(metric.metric_id, metric.label || metric.metric_id);
  const columns = [
    ['category_id', 'Category'], ['display_name', 'Pipeline'], ['suite_id', 'Suite'], ['runner_mode', 'Runner'],
    ...metricIds.map(id => [`metric:${id}`, metricLabels.get(id)]),
  ];
  const table = document.createElement('table'); table.className = 'results-table';
  const thead = document.createElement('thead'), headerRow = document.createElement('tr');
  for (const [key, label] of columns) {
    const th = document.createElement('th'); th.scope = 'col';
    const button = document.createElement('button'); button.type = 'button'; button.className = 'sort-button';
    const active = sort.key === key;
    button.textContent = `${label}${active ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ' ↕'}`;
    th.setAttribute('aria-sort', active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none');
    button.addEventListener('click', () => {
      sort = { key, direction: sort.key === key && sort.direction === 'asc' ? 'desc' : 'asc' };
      render();
    });
    th.append(button); headerRow.append(th);
  }
  thead.append(headerRow); table.append(thead);
  const tbody = document.createElement('tbody');
  for (const row of visible) {
    const tr = document.createElement('tr');
    const categoryCell = document.createElement('td');
    categoryCell.append(text('strong', labelCategory(row)));
    categoryCell.append(text('span', categories[row.category_id]?.description || row.task || '', 'table-subline'));
    tr.append(categoryCell, pipelineCell(row), text('td', row.suite_id));
    const runnerCell = document.createElement('td');
    runnerCell.append(text('span', row.runner_mode === 'submitter-owned' ? 'Submitter-owned' : 'Audio-bench', `tag ${row.runner_mode === 'submitter-owned' ? 'tag-owner' : 'tag-verified'}`));
    tr.append(runnerCell);
    const metrics = metricMap(row);
    for (const id of metricIds) {
      const metric = metrics.get(id), cell = document.createElement('td'); cell.className = 'metric-cell';
      if (metric) {
        cell.textContent = metric.display_value || metric.raw_display_value || String(metric.median ?? '—');
        if (Number.isFinite(metric.median)) cell.dataset.value = String(metric.median);
      } else cell.textContent = '—';
      tr.append(cell);
    }
    tbody.append(tr);
  }
  table.append(tbody); resultsHost.append(table);
}

async function main() {
  const response = await fetch(`data/results.json?refresh=${Date.now()}`, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error(`Could not load results (${response.status})`);
  const data = await response.json();
  if (data.schema_id !== 'audio-bench/site-results/0.1' || !Array.isArray(data.results)) throw new Error('Results index has an unsupported format.');
  records = data.results.map(row => ({
    ...row,
    category_id: row.category_id || (row.task?.toLowerCase().includes('filter') || row.provider_id === 'dsp.highpass80.v0'
      ? 'real-time-processing' : 'speech-enhancement'),
  }));
  const suites = [...new Set(records.map(row => row.suite_id).filter(Boolean))].sort();
  for (const value of suites) suiteFilter.append(new Option(value, value));
  document.querySelector('#result-count').textContent = String(records.length);
  document.querySelector('#pipeline-count').textContent = String(new Set(records.map(row => row.submission_id)).size);
  document.querySelector('#suite-count').textContent = String(suites.length);
  for (const control of [search, categoryFilter, runnerFilter, suiteFilter]) control.addEventListener('input', render);
  document.querySelector('#clear-filters').addEventListener('click', () => {
    search.value = ''; categoryFilter.value = ''; runnerFilter.value = ''; suiteFilter.value = ''; render();
  });
  render();
}
main().catch(error => { status.textContent = error.message; status.classList.add('error'); });
