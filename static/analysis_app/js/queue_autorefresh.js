(function () {
  const tableBody = document.getElementById('queue-table-body');
  if (!tableBody) return;

  const statusUrl = tableBody.dataset.statusUrl;
  if (!statusUrl) return;

  const pollIntervalMs = Number(tableBody.dataset.pollIntervalMs || 3000);
  const idleIntervalMs = Number(tableBody.dataset.idleIntervalMs || 12000);
  const warningNode = document.getElementById('queue-refresh-warning');

  const isActiveStatus = (status) => status === 'running' || status === 'queued';

  const renderStatus = (run) => {
    const normalizedStatus = String(run.status || '').toLowerCase();
    return `<span class="status-pill status-${normalizedStatus}">${normalizedStatus.toUpperCase()}</span>`;
  };

  const renderProgress = (run) => {
    if (!isActiveStatus(run.status)) {
      return '—';
    }
    return `
      <div class="progress-wrap"><div class="progress-bar" style="width: ${Number(run.progress_percent || 0)}%"></div></div>
      <div class="progress-text">${String(run.progress_label || '—')}</div>
    `;
  };

  const updateRow = (row, run) => {
    const statusCell = row.querySelector('.queue-status');
    const elapsedCell = row.querySelector('.queue-elapsed');
    const progressCell = row.querySelector('.queue-progress');

    if (statusCell) statusCell.innerHTML = renderStatus(run);
    if (elapsedCell) elapsedCell.textContent = run.elapsed_display || '—';
    if (progressCell) progressCell.innerHTML = renderProgress(run);
  };

  const hasActiveFromDom = () => Array.from(tableBody.querySelectorAll('tr[data-run-id]')).some((row) => {
    const statusPill = row.querySelector('.queue-status .status-pill');
    if (!statusPill) return false;
    const classes = Array.from(statusPill.classList);
    return classes.includes('status-running') || classes.includes('status-queued');
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
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json();
      const byRunId = new Map((payload.runs || []).map((run) => [run.run_id, run]));
      tableBody.querySelectorAll('tr[data-run-id]').forEach((row) => {
        const run = byRunId.get(row.dataset.runId);
        if (!run) return;
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
    const timeout = hasActive ? pollIntervalMs : idleIntervalMs;
    window.setTimeout(tick, timeout);
  };

  window.setTimeout(tick, hasActiveFromDom() ? pollIntervalMs : idleIntervalMs);
})();
