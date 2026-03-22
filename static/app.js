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

  // --- Shared State ---
  var lastQueryBody = null; // stored so export buttons can reuse it

  // --- Extension → file_type map ---
  var EXT_TO_TYPE = {
    '.pdf': 'pdf',
    '.epub': 'epub',
    '.txt': 'txt',
    '.text': 'txt',
    '.html': 'html',
    '.htm': 'html',
  };
  var SUPPORTED_EXTENSIONS = Object.keys(EXT_TO_TYPE);

  function fileTypeFromName(filename) {
    var ext = '.' + filename.split('.').pop().toLowerCase();
    return EXT_TO_TYPE[ext] || 'pdf';
  }

  // --- Query Interface ---
  var queryInput = document.getElementById('query-input');
  var querySubmit = document.getElementById('query-submit');
  var resultsSection = document.getElementById('query-results');
  var resultsHeader = document.getElementById('results-header');
  var resultsList = document.getElementById('results-list');

  if (querySubmit) {
    querySubmit.addEventListener('click', runQuery);
    queryInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') runQuery();
    });
  }

  function buildQueryBody() {
    var input = queryInput.value.trim();
    if (!input) return null;

    var lensFilters = {};
    ['temporal', 'epistemic', 'tradition', 'evidential_weight'].forEach(function (axis) {
      var sel = document.getElementById('filter-' + axis);
      if (sel) {
        var vals = Array.from(sel.selectedOptions).map(function (o) { return o.value; });
        if (vals.length > 0) lensFilters[axis] = vals;
      }
    });

    return {
      input_string: input,
      lens_filters: Object.keys(lensFilters).length ? lensFilters : null,
    };
  }

  async function runQuery() {
    var body = buildQueryBody();
    if (!body) return;

    lastQueryBody = body;
    querySubmit.disabled = true;
    querySubmit.textContent = 'Searching\u2026';

    try {
      var res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      var data = await res.json();
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
    var q = data.query;
    var m = data.compilation_metadata;

    resultsHeader.innerHTML =
      '<h3>' +
      escapeHtml(q.resolved_binomial || q.input_string) +
      '</h3>' +
      '<p class="meta">' +
      m.sources_hit +
      ' hits across ' +
      m.sources_queried +
      ' sources' +
      (m.sources_degraded ? ' \u00b7 ' + m.sources_degraded + ' degraded' : '') +
      '</p>';

    if (data.results.length === 0) {
      resultsList.innerHTML =
        '<p class="empty-state">No entries found. Try a different name or broaden your filters.</p>';
    } else {
      resultsList.innerHTML = data.results.map(renderResultCard).join('');
    }

    // Export buttons
    var exportBar = document.getElementById('results-export');
    if (!exportBar) {
      exportBar = document.createElement('div');
      exportBar.id = 'results-export';
      exportBar.className = 'results-export';
      resultsSection.appendChild(exportBar);
    }
    exportBar.innerHTML =
      '<button class="btn-primary" id="btn-compile-pdf">Compile Pr\u00e9cis PDF</button> ' +
      '<button class="btn-secondary" id="btn-export-json">Export JSON</button>';

    document.getElementById('btn-compile-pdf').addEventListener('click', function () {
      exportQuery('pdf');
    });
    document.getElementById('btn-export-json').addEventListener('click', function () {
      exportQuery('json');
    });

    resultsSection.classList.remove('hidden');
  }

  async function exportQuery(format) {
    if (!lastQueryBody) return;
    var btn = document.getElementById(format === 'pdf' ? 'btn-compile-pdf' : 'btn-export-json');
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = format === 'pdf' ? 'Compiling\u2026' : 'Exporting\u2026';

    try {
      var payload = Object.assign({}, lastQueryBody, { output_formats: [format] });
      var res = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      var data = await res.json();

      if (format === 'pdf') {
        if (data.pdf_error) {
          alert('PDF compilation failed: ' + data.pdf_error);
          return;
        }
        if (data.pdf_path) {
          var filename = data.pdf_path.split('/').pop();
          triggerDownload('/precis/' + encodeURIComponent(filename), filename);
        }
      } else {
        if (data.json_path) {
          var filename = data.json_path.split('/').pop();
          triggerDownload('/precis/' + encodeURIComponent(filename), filename);
        }
      }
    } catch (err) {
      alert('Export failed: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }

  function triggerDownload(url, filename) {
    var a = document.createElement('a');
    a.href = url;
    a.download = filename || '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function renderResultCard(r) {
    var s = r.source;
    var tags = [];
    Object.entries(s.lens_tags).forEach(function (entry) {
      var vals = Array.isArray(entry[1]) ? entry[1] : [entry[1]];
      vals.forEach(function (v) {
        if (v) tags.push(v);
      });
    });

    var flagHtml = r.flags.includes('degraded_ocr')
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
      tags.map(function (t) { return '<span class="tag">' + escapeHtml(t.replace(/_/g, ' ')) + '</span>'; }).join('') +
      flagHtml +
      '</div>' +
      '</div>'
    );
  }

  // --- Ingestion Interface ---
  var dropZone = document.getElementById('drop-zone');
  var fileInput = document.getElementById('file-input');

  if (dropZone) {
    dropZone.addEventListener('click', function () { fileInput.click(); });
    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', function () { dropZone.classList.remove('dragover'); });
    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', function () {
      if (fileInput.files.length) handleFile(fileInput.files[0]);
    });
  }

  async function handleFile(file) {
    var ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      alert('Unsupported format. Accepted: PDF, EPUB, TXT, HTML.');
      return;
    }
    var form = new FormData();
    form.append('file', file);

    try {
      var res = await fetch('/api/ingest/probe', { method: 'POST', body: form });
      var data = await res.json();
      showProbeResults(data, file.name);
    } catch (err) {
      alert('Probe failed: ' + err.message);
    }
  }

  function showProbeResults(data, filename) {
    var probeSection = document.getElementById('probe-results');
    var probeData = document.getElementById('probe-data');

    probeData.innerHTML =
      '<p>Pages: ' + data.total_pages + ' \u00b7 OCR confidence: ' +
      (data.ocr_confidence * 100).toFixed(0) + '%' +
      ' \u00b7 Template: ' + escapeHtml(data.suggested_template) +
      ' (' + (data.template_confidence * 100).toFixed(0) + '% confidence)</p>' +
      (data.ocr_confidence < 0.6
        ? '<p class="tag tag-degraded" style="display:inline-block;margin-top:0.5rem">Warning: degraded text quality. Fallback extraction will be used.</p>'
        : '');

    var idField = document.getElementById('meta-id');
    var fileField = document.getElementById('meta-file');
    var templateField = document.getElementById('meta-template');

    var baseName = filename.replace(/\.[^.]+$/, '').replace(/\s+/g, '_').toLowerCase();
    if (idField) idField.value = baseName;
    if (fileField) fileField.value = '_uploads/' + filename;
    if (templateField) templateField.value = data.suggested_template;

    probeSection.classList.remove('hidden');
  }

  var metaForm = document.getElementById('metadata-form');
  if (metaForm) {
    metaForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      var filePath = document.getElementById('meta-file').value;
      var metadata = {
        id: document.getElementById('meta-id').value,
        title: document.getElementById('meta-title').value,
        author: document.getElementById('meta-author').value,
        year: parseInt(document.getElementById('meta-year').value) || null,
        file: filePath,
        file_type: fileTypeFromName(filePath),
        extraction_template: document.getElementById('meta-template').value,
        lens_tags: {
          temporal: document.getElementById('lens-temporal').value,
          epistemic: document.getElementById('lens-epistemic').value,
          tradition: document.getElementById('lens-tradition').value,
          evidential_weight: document.getElementById('lens-evidential').value,
        },
      };

      var submitBtn = metaForm.querySelector('button[type="submit"]');
      submitBtn.disabled = true;
      submitBtn.textContent = 'Registering\u2026';

      try {
        var res = await fetch('/api/ingest/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(metadata),
        });
        var data = await res.json();

        // Trigger index build and poll for completion
        submitBtn.textContent = 'Indexing\u2026';
        fetch('/api/ingest/build-index/' + encodeURIComponent(data.id), { method: 'POST' });
        await pollIndexStatus(data.id, submitBtn);
      } catch (err) {
        alert('Registration failed: ' + err.message);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Register & Index';
      }
    });
  }

  async function pollIndexStatus(sourceId, statusEl) {
    var label = statusEl ? statusEl : null;
    var dotCount = 0;
    while (true) {
      await sleep(2000);
      try {
        var res = await fetch('/api/sources/' + encodeURIComponent(sourceId));
        var source = await res.json();

        if (source.index_status === 'ready') {
          if (label) {
            label.textContent = 'Indexed successfully';
            label.disabled = false;
            setTimeout(function () { label.textContent = 'Register & Index'; }, 3000);
          }
          return 'ready';
        }
        if (source.index_status === 'failed') {
          if (label) {
            label.textContent = 'Indexing failed';
            label.disabled = false;
            setTimeout(function () { label.textContent = 'Register & Index'; }, 3000);
          }
          return 'failed';
        }

        // Still building — update spinner
        dotCount = (dotCount + 1) % 4;
        if (label) label.textContent = 'Indexing' + '.'.repeat(dotCount + 1);
      } catch (err) {
        if (label) {
          label.textContent = 'Poll error';
          label.disabled = false;
        }
        return 'error';
      }
    }
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // --- Library Interface ---
  var sourcesBody = document.getElementById('sources-body');
  var sourcesEmpty = document.getElementById('sources-empty');

  if (sourcesBody) {
    loadSources();
  }

  async function loadSources() {
    try {
      var res = await fetch('/api/sources');
      var sources = await res.json();
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
    var ocrPct = ((s.ocr_confidence || 0) * 100).toFixed(0);
    var statusClass =
      s.index_status === 'ready'
        ? 'status-ready'
        : s.index_status === 'failed'
          ? 'status-failed'
          : 'status-pending';

    // Action buttons
    var actions = [];
    if (s.index_status === 'pending') {
      actions.push(
        '<button class="btn-secondary" onclick="buildIndex(\'' + escapeHtml(s.id) + '\', this)">Build Index</button>'
      );
    }
    if (s.index_status === 'ready' && !s.verified) {
      actions.push(
        '<button class="btn-secondary" onclick="verifySource(\'' + escapeHtml(s.id) + '\')">Verify</button>'
      );
    }
    actions.push(
      '<button class="btn-secondary" onclick="deleteSource(\'' + escapeHtml(s.id) + '\')">Remove</button>'
    );

    return (
      '<tr>' +
      '<td>' + escapeHtml(s.title) + '</td>' +
      '<td>' + escapeHtml(s.author) + '</td>' +
      '<td>' + (s.year || '\u2014') + '</td>' +
      '<td>' + escapeHtml(s.extraction_template || '') + '</td>' +
      '<td><span class="ocr-bar"><span class="ocr-bar-fill" style="width:' + ocrPct + '%"></span></span> ' + ocrPct + '%</td>' +
      '<td><span class="status-badge ' + statusClass + '">' + escapeHtml(s.index_status) + '</span></td>' +
      '<td>' + (s.verified ? 'Yes' : '\u2014') + '</td>' +
      '<td class="actions-cell">' + actions.join(' ') + '</td>' +
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

  window.verifySource = async function (id) {
    try {
      var res = await fetch('/api/sources/' + encodeURIComponent(id) + '/verify', {
        method: 'PATCH',
      });
      if (!res.ok) {
        var data = await res.json();
        alert('Verify failed: ' + (data.detail || 'Unknown error'));
        return;
      }
      loadSources();
    } catch (err) {
      alert('Verify failed: ' + err.message);
    }
  };

  window.buildIndex = async function (id, btn) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Indexing\u2026';
    }
    try {
      fetch('/api/ingest/build-index/' + encodeURIComponent(id), { method: 'POST' });
      var status = await pollIndexStatus(id, btn);
      loadSources();
    } catch (err) {
      alert('Index build failed: ' + err.message);
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Build Index';
      }
    }
  };

  // Export manifest
  var exportBtn = document.getElementById('export-manifest');
  if (exportBtn) {
    exportBtn.addEventListener('click', async function () {
      try {
        var res = await fetch('/api/sources');
        var sources = await res.json();
        var manifest = { schema_version: '2.0', sources: sources };
        var blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'library_manifest.json';
        a.click();
      } catch (err) {
        alert('Export failed: ' + err.message);
      }
    });
  }

  // Import manifest
  var importInput = document.getElementById('import-manifest-input');
  if (importInput) {
    importInput.addEventListener('change', async function () {
      var file = importInput.files[0];
      if (!file) return;

      var text = await file.text();
      var manifest;
      try {
        manifest = JSON.parse(text);
      } catch (err) {
        alert('Invalid JSON: ' + err.message);
        return;
      }

      var sources = manifest.sources;
      if (!Array.isArray(sources) || sources.length === 0) {
        alert('No sources found in manifest.');
        return;
      }

      var imported = 0;
      var failed = 0;
      for (var i = 0; i < sources.length; i++) {
        var s = sources[i];
        try {
          var res = await fetch('/api/ingest/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(s),
          });
          if (res.ok) {
            imported++;
          } else {
            failed++;
          }
        } catch (err) {
          failed++;
        }
      }

      alert('Imported ' + imported + ' source(s)' + (failed ? ', ' + failed + ' failed' : '') +
        '.\nUse "Build Index" in the library to index each source.');
      importInput.value = '';
      if (sourcesBody) loadSources();
    });
  }

  // --- Util ---
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
})();
