/* Plant Précis Producer — Frontend Logic */

(function () {
  'use strict';

  // --- Theme Toggle ---
  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    toggle.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme');
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
    });
  }

  // --- Query Interface ---
  const queryInput = document.getElementById('query-input');
  const querySubmit = document.getElementById('query-submit');
  const resultsSection = document.getElementById('query-results');
  const resultsHeader = document.getElementById('results-header');
  const resultsList = document.getElementById('results-list');

  if (querySubmit) {
    querySubmit.addEventListener('click', runQuery);
    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') runQuery();
    });
  }

  async function runQuery() {
    const input = queryInput.value.trim();
    if (!input) return;

    querySubmit.disabled = true;
    querySubmit.textContent = 'Searching…';

    const lensFilters = {};
    ['temporal', 'epistemic', 'tradition', 'evidential_weight'].forEach((axis) => {
      const sel = document.getElementById('filter-' + axis);
      if (sel) {
        const vals = Array.from(sel.selectedOptions).map((o) => o.value);
        if (vals.length > 0) lensFilters[axis] = vals;
      }
    });

    try {
      const res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_string: input,
          lens_filters: Object.keys(lensFilters).length ? lensFilters : null,
        }),
      });
      const data = await res.json();
      renderResults(data);
    } catch (err) {
      resultsHeader.innerHTML = '<h3>Error</h3><p class="meta">' + err.message + '</p>';
      resultsList.innerHTML = '';
      resultsSection.classList.remove('hidden');
    } finally {
      querySubmit.disabled = false;
      querySubmit.textContent = 'Search';
    }
  }

  function renderResults(data) {
    const q = data.query;
    const m = data.compilation_metadata;

    resultsHeader.innerHTML =
      '<h3>' +
      escapeHtml(q.resolved_binomial || q.input_string) +
      '</h3>' +
      '<p class="meta">' +
      m.sources_hit +
      ' hits across ' +
      m.sources_queried +
      ' sources' +
      (m.sources_degraded ? ' · ' + m.sources_degraded + ' degraded' : '') +
      '</p>';

    if (data.results.length === 0) {
      resultsList.innerHTML =
        '<p class="empty-state">No entries found. Try a different name or broaden your filters.</p>';
    } else {
      resultsList.innerHTML = data.results.map(renderResultCard).join('');
    }

    resultsSection.classList.remove('hidden');
  }

  function renderResultCard(r) {
    const s = r.source;
    const tags = [];
    Object.entries(s.lens_tags).forEach(([axis, vals]) => {
      (Array.isArray(vals) ? vals : [vals]).forEach((v) => {
        if (v) tags.push(v);
      });
    });

    const flagHtml = r.flags.includes('degraded_ocr')
      ? '<span class="tag tag-degraded">degraded</span>'
      : '';

    return (
      '<div class="result-card">' +
      '<div class="result-source">' +
      escapeHtml(s.title) +
      '</div>' +
      '<div class="result-citation">' +
      escapeHtml(r.citation) +
      '</div>' +
      '<div class="result-tags">' +
      tags.map((t) => '<span class="tag">' + escapeHtml(t.replace(/_/g, ' ')) + '</span>').join('') +
      flagHtml +
      '</div>' +
      '</div>'
    );
  }

  // --- Ingestion Interface ---
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  if (dropZone) {
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) handleFile(fileInput.files[0]);
    });
  }

  const SUPPORTED_EXTENSIONS = ['.pdf', '.epub', '.txt', '.text', '.html', '.htm'];

  async function handleFile(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      alert('Unsupported format. Accepted: PDF, EPUB, TXT, HTML.');
      return;
    }
    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch('/api/ingest/probe', { method: 'POST', body: form });
      const data = await res.json();
      showProbeResults(data, file.name);
    } catch (err) {
      alert('Probe failed: ' + err.message);
    }
  }

  function showProbeResults(data, filename) {
    const probeSection = document.getElementById('probe-results');
    const probeData = document.getElementById('probe-data');

    probeData.innerHTML =
      '<p>Pages: ' + data.total_pages + ' · OCR confidence: ' +
      (data.ocr_confidence * 100).toFixed(0) + '%' +
      ' · Template: ' + escapeHtml(data.suggested_template) +
      ' (' + (data.template_confidence * 100).toFixed(0) + '% confidence)</p>' +
      (data.ocr_confidence < 0.6
        ? '<p class="tag tag-degraded" style="display:inline-block;margin-top:0.5rem">Warning: degraded text quality. Fallback extraction will be used.</p>'
        : '');

    const idField = document.getElementById('meta-id');
    const fileField = document.getElementById('meta-file');
    const templateField = document.getElementById('meta-template');

    if (idField) idField.value = filename.replace('.pdf', '').replace(/\s+/g, '_').toLowerCase();
    if (fileField) fileField.value = filename;
    if (templateField) templateField.value = data.suggested_template;

    probeSection.classList.remove('hidden');
  }

  const metaForm = document.getElementById('metadata-form');
  if (metaForm) {
    metaForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const metadata = {
        id: document.getElementById('meta-id').value,
        title: document.getElementById('meta-title').value,
        author: document.getElementById('meta-author').value,
        year: parseInt(document.getElementById('meta-year').value) || null,
        file: document.getElementById('meta-file').value,
        file_type: 'pdf',
        extraction_template: document.getElementById('meta-template').value,
        lens_tags: {
          temporal: document.getElementById('lens-temporal').value,
          epistemic: document.getElementById('lens-epistemic').value,
          tradition: document.getElementById('lens-tradition').value,
          evidential_weight: document.getElementById('lens-evidential').value,
        },
      };

      try {
        const res = await fetch('/api/ingest/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(metadata),
        });
        const data = await res.json();

        // Trigger index build
        await fetch('/api/ingest/build-index/' + encodeURIComponent(data.id), {
          method: 'POST',
        });
        alert('Source registered and indexed: ' + data.id);
      } catch (err) {
        alert('Registration failed: ' + err.message);
      }
    });
  }

  // --- Library Interface ---
  const sourcesBody = document.getElementById('sources-body');
  const sourcesEmpty = document.getElementById('sources-empty');

  if (sourcesBody) {
    loadSources();
  }

  async function loadSources() {
    try {
      const res = await fetch('/api/sources');
      const sources = await res.json();
      if (sources.length === 0) {
        sourcesEmpty.style.display = '';
        return;
      }
      sourcesEmpty.style.display = 'none';
      sourcesBody.innerHTML = sources.map(renderSourceRow).join('');
    } catch (err) {
      sourcesEmpty.textContent = 'Failed to load sources.';
    }
  }

  function renderSourceRow(s) {
    const ocrPct = ((s.ocr_confidence || 0) * 100).toFixed(0);
    const statusClass =
      s.index_status === 'ready'
        ? 'status-ready'
        : s.index_status === 'failed'
          ? 'status-failed'
          : 'status-pending';

    return (
      '<tr>' +
      '<td>' + escapeHtml(s.title) + '</td>' +
      '<td>' + escapeHtml(s.author) + '</td>' +
      '<td>' + (s.year || '—') + '</td>' +
      '<td>' + escapeHtml(s.extraction_template || '') + '</td>' +
      '<td><span class="ocr-bar"><span class="ocr-bar-fill" style="width:' + ocrPct + '%"></span></span> ' + ocrPct + '%</td>' +
      '<td><span class="status-badge ' + statusClass + '">' + escapeHtml(s.index_status) + '</span></td>' +
      '<td>' + (s.verified ? 'Yes' : '—') + '</td>' +
      '<td><button class="btn-secondary" onclick="deleteSource(\'' + escapeHtml(s.id) + '\')">Remove</button></td>' +
      '</tr>'
    );
  }

  window.deleteSource = async function (id) {
    if (!confirm('Remove source "' + id + '" from the library?')) return;
    try {
      await fetch('/api/sources/' + encodeURIComponent(id), { method: 'DELETE' });
      loadSources();
    } catch (err) {
      alert('Failed to delete: ' + err.message);
    }
  };

  // Export manifest
  const exportBtn = document.getElementById('export-manifest');
  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/sources');
        const sources = await res.json();
        const manifest = { schema_version: '2.0', sources: sources };
        const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'library_manifest.json';
        a.click();
      } catch (err) {
        alert('Export failed: ' + err.message);
      }
    });
  }

  // --- Util ---
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
})();
