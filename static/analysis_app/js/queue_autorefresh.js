(function () {
  const tableBody = document.getElementById('queue-table-body');
  if (!tableBody) return;

  const statusUrl = tableBody.dataset.statusUrl;
  if (!statusUrl) return;

  const pollIntervalMs = Number(tableBody.dataset.pollIntervalMs || 3000);
  const idleIntervalMs = Number(tableBody.dataset.idleIntervalMs || 10000);
  const warningNode = document.getElementById('queue-refresh-warning');

  const isActiveStatus = (status) => status === 'running' || status === 'queued';

  const updateRow = (row, run) => {
    const normalizedStatus = String(run.status || '').toLowerCase();
    const badge = row.querySelector('[data-role="status-badge"]');
    if (badge) {
      badge.textContent = normalizedStatus.toUpperCase();
      badge.className = `status-pill status-${normalizedStatus}`;
    }

    const elapsed = row.querySelector('[data-role="elapsed"]');
    if (elapsed) {
      elapsed.textContent = run.elapsed_display || '—';
    }

    const progressCell = row.querySelector('.queue-progress');
    if (!progressCell) return;

    let progressText = row.querySelector('[data-role="progress-text"]');
    let progressBar = row.querySelector('[data-role="progress-bar"]');

    if (isActiveStatus(normalizedStatus)) {
      if (!progressText || !progressBar) {
        progressCell.innerHTML = '<div class="progress-wrap"><div data-role="progress-bar" class="progress-bar"></div></div><div data-role="progress-text" class="progress-text"></div>';
        progressText = row.querySelector('[data-role="progress-text"]');
        progressBar = row.querySelector('[data-role="progress-bar"]');
      }
      progressBar.style.width = `${Number(run.progress_percent || 0)}%`;
      progressText.textContent = String(run.progress_label || '—');
    } else {
      progressCell.textContent = '—';
    }
  };

  const hasActiveFromDom = () => Array.from(tableBody.querySelectorAll('tr[data-run-id]')).some((row) => {
    const badge = row.querySelector('[data-role="status-badge"]');
    if (!badge) return false;
    return badge.classList.contains('status-running') || badge.classList.contains('status-queued');
  });

  const setWarning = (show) => {
    if (!warningNode) return;
    warningNode.hidden = !show;
  };

  const poll = async () => {
    try {
      const response = await fetch(statusUrl, {
        method: 'GET',
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload = await response.json();
      const byRunId = new Map((payload.runs || []).map((run) => [run.run_id, run]));
      tableBody.querySelectorAll('tr[data-run-id]').forEach((row) => {
        const run = byRunId.get(row.dataset.runId);
        if (!run) {
          row.remove();
          return;
        }
        updateRow(row, run);
      });
      setWarning(false);
      return (payload.runs || []).some((run) => isActiveStatus(String(run.status || '').toLowerCase()));
    } catch (_error) {
      setWarning(true);
      return hasActiveFromDom();
    }
  };

  const tick = async () => {
    const hasActive = await poll();
    window.setTimeout(tick, hasActive ? pollIntervalMs : idleIntervalMs);
  };

  window.setTimeout(tick, hasActiveFromDom() ? pollIntervalMs : idleIntervalMs);
})();
