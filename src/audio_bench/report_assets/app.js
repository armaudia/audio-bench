/* SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
 * SPDX-License-Identifier: Apache-2.0
 */
const errorBox = document.querySelector('#error');
const tbody = document.querySelector('#rows-body');
const params = new URLSearchParams(location.search);
const filters = [['filter-task', 'task'], ['filter-cohort', 'cohort'], ['filter-config', 'config']];
let allRows = [];

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}
function option(select, value, label = value) {
  const item = document.createElement('option');
  item.value = value;
  item.textContent = label;
  select.append(item);
}
function badge(kind, value) {
  const span = document.createElement('span');
  span.className = `badge badge-${value}`;
  span.textContent = `${kind}: ${value}`;
  return span;
}
function validateQuery(rows) {
  const tasks = new Set(rows.map(row => row.task));
  const cohorts = new Set(rows.map(row => row.comparison_cohort_id));
  const configs = new Set(rows.map(row => row.configuration_id));
  for (const [key, values] of [['task', tasks], ['cohort', cohorts], ['config', configs]]) {
    const value = params.get(key);
    if (value && !values.has(value)) throw new Error(`Unknown ${key} ID in query: ${value}`);
  }
}
function visibleRows(rows) {
  return rows.filter(row =>
    (!params.get('task') || row.task === params.get('task')) &&
    (!params.get('cohort') || row.comparison_cohort_id === params.get('cohort')) &&
    (!params.get('config') || row.configuration_id === params.get('config')));
}
function render(rows) {
  document.querySelector('#result-status').textContent = `Showing ${rows.length} of ${allRows.length} configurations`;
  document.querySelector('#csv-export').disabled = !rows.length;
  tbody.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const value of [row.configuration_id, row.comparison_cohort_id, row.task, row.hardware]) {
      const td = document.createElement('td');
      if (value === row.configuration_id || value === row.comparison_cohort_id) {
        const code = document.createElement('code');
        code.textContent = value;
        td.append(code);
      } else td.textContent = value;
      tr.append(td);
    }
    const metricCell = document.createElement('td');
    for (const attempt of row.attempts) {
      for (const [id, metric] of Object.entries(attempt.metrics)) {
        const p = document.createElement('p');
        p.textContent = `${attempt.attempt_id} / ${id}: mean ${metric.mean ?? 'undefined'} (finite n=${metric.finite_count})`;
        metricCell.append(p);
      }
    }
    tr.append(metricCell);
    const badgeCell = document.createElement('td');
    for (const [key, value] of Object.entries(row.badges)) badgeCell.append(badge(key, value));
    for (const attempt of row.attempts) {
      const p = document.createElement('p');
      p.textContent = `Attempt ${attempt.attempt_id}: ${attempt.status}; counts ${JSON.stringify(attempt.counts)}`;
      for (const [key, value] of Object.entries(attempt.badges)) p.append(' ', badge(key, value));
      badgeCell.append(p);
    }
    tr.append(badgeCell);
    tbody.append(tr);
  }
}
function csvCell(value) {
  let text = value == null ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
function exportVisibleCsv() {
  const visible = visibleRows(allRows);
  const lines = [['configuration_id', 'comparison_cohort_id', 'task', 'attempt_id', 'metric_id',
    'finite_count', 'mean', 'median', 'execution', 'review', 'reproduction', 'qualification']];
  for (const row of visible) {
    for (const attempt of row.attempts) {
      for (const [metric, value] of Object.entries(attempt.metrics)) {
        lines.push([row.configuration_id, row.comparison_cohort_id, row.task, attempt.attempt_id, metric,
          value.finite_count, value.mean, value.median, attempt.badges.execution, attempt.badges.review,
          attempt.badges.reproduction, attempt.badges.qualification]);
      }
    }
  }
  const content = lines.map(line => line.map(csvCell).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'visible-evidence-rows.csv';
  link.click();
  URL.revokeObjectURL(url);
}
function applyFilters() {
  for (const [id, key] of filters) {
    const value = document.getElementById(id).value;
    if (value) params.set(key, value); else params.delete(key);
  }
  const next = new URL(location.href);
  next.search = params.toString();
  history.replaceState(null, '', next);
  render(visibleRows(allRows));
}
async function main() {
  const response = await fetch('data/index.json', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`Index load failed: HTTP ${response.status}`);
  const index = await response.json();
  allRows = index.rows;
  validateQuery(index.rows);
  const tasks = [...new Set(index.rows.map(row => row.task))].sort();
  const cohorts = [...new Set(index.rows.map(row => row.comparison_cohort_id))].sort();
  const configs = [...new Set(index.rows.map(row => row.configuration_id))].sort();
  tasks.forEach(value => option(document.querySelector('#filter-task'), value));
  cohorts.forEach(value => option(document.querySelector('#filter-cohort'), value));
  configs.forEach(value => option(document.querySelector('#filter-config'), value));
  for (const [id, key] of filters) {
    const value = params.get(key);
    if (value) document.getElementById(id).value = value;
  }
  render(visibleRows(index.rows));
  document.querySelector('#filter-form').addEventListener('submit', event => {
    event.preventDefault();
    applyFilters();
  });
  document.querySelector('#reset-filters').addEventListener('click', () => {
    for (const [id] of filters) document.getElementById(id).value = '';
    applyFilters();
  });
  document.querySelector('#csv-export').addEventListener('click', exportVisibleCsv);
}
main().catch(error => showError(error.message));
