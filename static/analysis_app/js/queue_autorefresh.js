(function () {
  const tableBody = document.getElementById('queue-table-body');
  if (!tableBody) return;

  const statusUrl = tableBody.dataset.statusUrl;
  if (!statusUrl) return;

  const pollIntervalMs = Number(tableBody.dataset.pollIntervalMs || 3000);
  const idleIntervalMs = Number(tableBody.dataset.idleIntervalMs || 10000);
  const warningNode = document.getElementById('queue-refresh-warning');

  const isActiveStatus = (status) => status === 'running' || status === 'queued';

  const renderActions = (row, run) => {
    const actionCell = row.querySelector('.queue-action');
    if (!actionCell) return;

    const actionsInline = actionCell.querySelector('.actions-inline');
    if (!actionsInline) return;

    const openLink = actionsInline.querySelector('[data-role="open-link"]');
    if (run.has_results && run.results_url) {
      if (!openLink) {
        const link = document.createElement('a');
        link.className = 'primary';
        link.target = '_blank';
        link.rel = 'noopener';
        link.setAttribute('data-role', 'open-link');
        link.textContent = 'Открыть';
        actionsInline.prepend(link);
      }
      actionsInline.querySelector('[data-role="open-link"]').href = run.results_url;
    } else if (openLink) {
      openLink.remove();
    }

    const debugLink = actionsInline.querySelector('[data-role="debug-link"]');
    if (run.debug_available && run.debug_zip_url) {
      if (!debugLink) {
        const link = document.createElement('a');
        link.target = '_blank';
        link.rel = 'noopener';
        link.setAttribute('data-role', 'debug-link');
        link.textContent = 'Debug';
        const deleteForm = actionsInline.querySelector('form');
        if (deleteForm) {
          actionsInline.insertBefore(link, deleteForm);
        } else {
          actionsInline.appendChild(link);
        }
      }
      actionsInline.querySelector('[data-role="debug-link"]').href = run.debug_zip_url;
    } else if (debugLink) {
      debugLink.remove();
    }

    let details = actionCell.querySelector('[data-role="queue-details"]');
    if (!isActiveStatus(String(run.status || '').toLowerCase()) && run.error_message) {
      if (!details) {
        details = document.createElement('div');
        details.className = 'muted';
        details.setAttribute('data-role', 'queue-details');
        actionCell.appendChild(details);
      }
      details.textContent = run.error_message;
    } else if (details) {
      details.remove();
    }
  };

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

    const startedAt = row.querySelector('[data-role="started-at"]');
    if (startedAt) {
      startedAt.textContent = run.started_at_display || '—';
    }

    renderActions(row, run);

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
