const resultsHost = document.querySelector('#results');
const status = document.querySelector('#status');
const search = document.querySelector('#search');
const runnerFilter = document.querySelector('#runner-filter');
const suiteFilter = document.querySelector('#suite-filter');
let records = [];

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
  } catch {
    return null;
  }
}

function render() {
  const term = search.value.trim().toLowerCase();
  const runner = runnerFilter.value;
  const suite = suiteFilter.value;
  const visible = records.filter(row => {
    const content = [row.display_name, row.provider_id, row.source?.repository].join(' ').toLowerCase();
    return (!term || content.includes(term)) && (!runner || row.runner_mode === runner) && (!suite || row.suite_id === suite);
  });
  resultsHost.replaceChildren();
  if (!visible.length) {
    resultsHost.append(text('p', records.length ? 'No results match those filters.' : 'No validated main-branch benchmark run has been published yet.', 'empty'));
    status.textContent = records.length ? `0 of ${records.length} results` : 'Results are empty';
    return;
  }
  status.textContent = `Showing ${visible.length} of ${records.length} results`;
  for (const row of visible) {
    const card = document.createElement('article');
    card.className = 'result-card';
    const top = document.createElement('div'); top.className = 'card-top';
    top.append(text('span', row.runner_mode === 'submitter-owned' ? 'Submitter-run' : 'Audio-bench-run', `tag ${row.runner_mode === 'submitter-owned' ? 'tag-owner' : 'tag-verified'}`));
    top.append(text('span', row.result_status || 'published', 'run-state'));
    card.append(top, text('h3', row.display_name), text('p', `${row.task || 'Noise cancellation'} · ${row.suite_id || 'suite pending'}`, 'subline'));
    const metricList = document.createElement('dl'); metricList.className = 'metrics';
    for (const metric of (row.metrics || [])) {
      metricList.append(text('dt', metric.label || metric.metric_id), text('dd', metric.raw_display_value ?? metric.display_value ?? '—'));
      if (Number.isFinite(metric.mean)) {
        metricList.append(text('dt', `${metric.label || metric.metric_id} · mean`, ''), text('dd', `${metric.mean.toPrecision(4)} ${metric.unit || ''}`.trim(), 'muted'));
      }
      if (Array.isArray(metric.median_interval_95) && metric.median_interval_95.length === 2) {
        const [low, high] = metric.median_interval_95;
        metricList.append(text('dt', 'Within-cohort 95% interval', ''),
          text('dd', `${low.toPrecision(4)} to ${high.toPrecision(4)} ${metric.unit || ''}`.trim(), 'muted'));
      }
      if (metric.normalized_display_value) {
        metricList.append(text('dt', 'Estimated on audio-bench runner'), text('dd', metric.normalized_display_value));
      }
    }
    if (!row.metrics?.length) metricList.append(text('dt', 'Result', 'muted'), text('dd', 'Awaiting measurements', 'muted'));
    card.append(metricList);
    const meta = document.createElement('div'); meta.className = 'provenance';
    meta.append(text('span', `Provider ${row.provider_id || '—'}`));
    if (row.source?.visibility === 'private') {
      meta.append(text('span', `Private source identity ${row.source.repository_identity_sha256 || '—'}`));
      meta.append(text('span', `Source commit ${row.source.revision || '—'}`));
    } else {
      meta.append(text('span', `Source ${row.source?.revision || '—'}`));
    }
    meta.append(text('span', `Model ${row.model_digest || 'not applicable'}`));
    meta.append(text('span', `Dataset ${row.dataset_label || row.dataset_id || '—'}`));
    if (row.case_count) meta.append(text('span', `${row.case_count} paired utterances`));
    const protocolUrl = safeHttpUrl(row.protocol_url);
    if (protocolUrl) {
      const link = document.createElement('a'); link.href = protocolUrl; link.rel = 'noreferrer'; link.textContent = 'View scoring protocol →'; meta.append(link);
    }
    const datasetUrl = safeHttpUrl(row.dataset_source_url);
    if (datasetUrl) {
      const link = document.createElement('a'); link.href = datasetUrl; link.rel = 'noreferrer'; link.textContent = 'Dataset source →'; meta.append(link);
    }
    if (row.runner_mode === 'submitter-owned') meta.append(text('span', 'Not independently verified', 'warning'));
    const sourceUrl = row.source?.visibility === 'private' ? null : safeHttpUrl(row.source?.url);
    if (sourceUrl) {
      const link = document.createElement('a'); link.href = sourceUrl; link.rel = 'noreferrer'; link.textContent = 'View source →'; meta.append(link);
    }
    const resultUrl = safeHttpUrl(row.result_url);
    if (resultUrl) {
      const link = document.createElement('a'); link.href = resultUrl; link.rel = 'noreferrer'; link.textContent = 'Evidence record →'; meta.append(link);
    }
    card.append(meta);
    if (row.evidence) {
      const details = document.createElement('details'); details.className = 'evidence-details';
      details.append(text('summary', 'Measurement provenance'));
      const evidence = document.createElement('div'); evidence.className = 'provenance';
      for (const [label, value] of [
        ['SDK package', row.evidence.sdk_package_digest],
        ['Harness', row.evidence.harness_digest],
        ['Dataset manifest', row.evidence.dataset_manifest_digest],
        ['Case manifest', row.evidence.case_manifest_digest],
        ['Scoring protocol', row.evidence.protocol_digest],
        ['Candidate package', row.evidence.candidate_package_digest],
        ['Provider plugin', row.evidence.provider_plugin_digest],
        ['Provider descriptor', row.evidence.provider_descriptor_digest],
        ['Configuration', row.evidence.configuration_id],
        ['Bundle', row.evidence.bundle_manifest_digest],
        ['Runner', row.evidence.runner_fingerprint],
        ['Reference latency on submitter runner', row.evidence.reference_raw_latency_ms ? `${row.evidence.reference_raw_latency_ms} ms` : null],
        ['Candidate latency on submitter runner', row.evidence.candidate_raw_latency_ms ? `${row.evidence.candidate_raw_latency_ms} ms` : null],
        ['Reference latency on audio-bench runner', row.evidence.reference_baseline_latency_ms ? `${row.evidence.reference_baseline_latency_ms} ms` : null],
      ]) if (value) evidence.append(text('span', `${label} ${value}`));
      details.append(evidence);
      card.append(details);
    }
    resultsHost.append(card);
  }
}

async function main() {
  const response = await fetch('data/results.json', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`Could not load results (${response.status})`);
  const data = await response.json();
  if (data.schema_id !== 'audio-bench/site-results/0.1' || !Array.isArray(data.results)) throw new Error('Results index has an unsupported format.');
  records = data.results;
  const suites = [...new Set(records.map(row => row.suite_id).filter(Boolean))].sort();
  for (const value of suites) suiteFilter.append(new Option(value, value));
  document.querySelector('#result-count').textContent = String(records.length);
  document.querySelector('#pipeline-count').textContent = String(new Set(records.map(row => row.submission_id)).size);
  document.querySelector('#suite-count').textContent = String(suites.length);
  for (const control of [search, runnerFilter, suiteFilter]) control.addEventListener('input', render);
  document.querySelector('#clear-filters').addEventListener('click', () => { search.value = ''; runnerFilter.value = ''; suiteFilter.value = ''; render(); });
  render();
}
main().catch(error => { status.textContent = error.message; status.classList.add('error'); });
