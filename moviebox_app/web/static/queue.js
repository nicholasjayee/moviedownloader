import {bytes, element} from './format.js';

const $ = (selector) => document.querySelector(selector);

function action(label, job, kind) {
  const button = element('button', 'secondary', label);
  button.type = 'button';
  button.dataset.job = job.id;
  button.dataset.action = kind;
  button.setAttribute('aria-label', `${label} ${job.title}`);
  return button;
}

export function renderQueue(jobs, filter, hasMore, queue = null) {
  const search = $('#search').value.toLocaleLowerCase();
  const active = jobs.filter((job) => ['queued', 'downloading'].includes(job.status));
  $('#count').textContent = jobs.length + (hasMore ? '+' : '');
  $('#activity').textContent = queue ?
    `${queue.downloading} downloading · ${queue.queued} waiting` :
    active.length ? `${active.length} queued or downloading` : 'No active downloads';
  $('#activity').title = queue ? `Up to ${queue.concurrency} downloads at once` : '';
  const visible = jobs.filter((job) => {
    const matches = filter === 'all' || (filter === 'active' && active.includes(job)) ||
      (filter === 'failed' && ['failed', 'cancelled'].includes(job.status)) || job.status === filter;
    return matches && job.title.toLocaleLowerCase().includes(search);
  });
  const container = $('#downloads');
  // Retain keyboard focus while progress updates redraw the list.
  const focused = document.activeElement?.dataset;
  const focusedJob = focused?.job;
  const focusedAction = focused?.action;
  container.replaceChildren();
  for (const job of visible) {
    const row = element('article', 'download');
    row.append(element('div', 'file-mark', job.filename.split('.').pop().toUpperCase()));
    const content = element('div', 'download-body');
    content.append(element('h3', '', job.title));
    const meta = element('div', 'metadata');
    meta.append(element('span', `status ${job.status}`, job.status[0].toUpperCase() + job.status.slice(1)));
    let details = ` · ${bytes(job.downloaded_bytes)}`;
    if (job.total_bytes != null) details += ` / ${bytes(job.total_bytes)}`;
    if (job.status === 'downloading') {
      details += ` · ${bytes(job.speed_bytes)}/s`;
      if (job.progress != null) details += ` · ${job.progress}%`;
      if (job.speed_bytes > 0 && job.total_bytes) {
        const minutes = Math.ceil((job.total_bytes - job.downloaded_bytes) / job.speed_bytes / 60);
        details += ` · ${minutes < 1 ? '<1' : minutes} min left`;
      }
    }
    meta.append(document.createTextNode(details));
    content.append(meta);
    if (job.status === 'downloading' || job.status === 'queued') {
      const track = element('div', `progress-track${job.progress == null ? ' indeterminate' : ''}`);
      const fill = element('div', 'progress-fill');
      fill.style.width = job.progress == null ? '25%' : `${job.progress}%`;
      track.setAttribute('role', 'progressbar');
      track.setAttribute('aria-label', `${job.title} download progress`);
      if (job.progress != null) track.setAttribute('aria-valuenow', job.progress);
      track.append(fill);
      content.append(track);
    }
    if (job.error) content.append(element('p', 'job-error', job.error));
    row.append(content);
    const actions = element('div', 'actions');
    if (['queued', 'downloading'].includes(job.status)) actions.append(action('Cancel', job, 'cancel'));
    if (['failed', 'cancelled'].includes(job.status)) actions.append(action('Retry', job, 'retry'));
    if (job.status === 'completed') {
      const link = element('a', 'secondary', 'Save file ↓');
      link.href = `/api/downloads/${job.id}/file`;
      link.dataset.job = job.id;
      link.dataset.action = 'file';
      actions.append(link);
    }
    row.append(actions);
    container.append(row);
  }
  if (focusedJob) {
    Array.from(container.querySelectorAll('[data-job]')).find((node) =>
      node.dataset.job === focusedJob && node.dataset.action === focusedAction)?.focus({preventScroll: true});
  }
  $('#empty').hidden = visible.length > 0;
  $('#empty h3').textContent = jobs.length ? 'No matching downloads.' : 'Room for your next movie.';
  $('#empty p').textContent = jobs.length ? 'Try another filter or search.' : 'Search for a movie above and choose a quality to start downloading.';
  $('#load-more').hidden = !hasMore;
}
