import {api} from './api.js';
import {renderQueue} from './queue.js';
import {setupMovieSearch} from './movie-search.js';

const $ = (selector) => document.querySelector(selector);
let jobs = [];
let queue = null;
let filter = 'all';
let limit = 50;
let hasMore = false;
let pollTimer;
let refreshVersion = 0;

function render() {
  renderQueue(jobs, filter, hasMore, queue);
}

function showError(selector, message = '') {
  $(selector).textContent = message;
  $(selector).hidden = !message;
}

async function refresh() {
  clearTimeout(pollTimer);
  const version = ++refreshVersion;
  try {
    const result = await api(`/downloads?limit=${limit}`);
    if (version !== refreshVersion) return;
    jobs = result.downloads;
    queue = result.queue;
    hasMore = jobs.length === limit && limit < 200;
    $('#connection').textContent = 'Local server connected';
    $('#connection').classList.add('online');
    render();
  } catch {
    if (version !== refreshVersion) return;
    $('#connection').textContent = 'Connection lost · retrying';
    $('#connection').classList.remove('online');
  } finally {
    const busy = jobs.some((job) => ['queued', 'downloading'].includes(job.status));
    if (version === refreshVersion) {
      pollTimer = setTimeout(refresh, document.hidden ? 10000 : busy ? 1000 : 4000);
    }
  }
}

$('#download-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  showError('#form-error');
  const button = $('#submit');
  button.disabled = true;
  try {
    await api('/downloads', {method: 'POST', body: JSON.stringify({url: $('#url').value.trim(), title: $('#title').value.trim()})});
    event.target.reset();
    filter = 'all';
    setFilterButtons();
    await refresh();
    $('#url').focus();
  } catch (error) { showError('#form-error', error.message); }
  finally { button.disabled = false; }
});

$('#downloads').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  button.disabled = true;
  showError('#action-error');
  try {
    await api(`/downloads/${button.dataset.job}/${button.dataset.action}`, {method: 'POST'});
    await refresh();
  } catch (error) { showError('#action-error', error.message); }
  finally { button.disabled = false; }
});

function setFilterButtons() {
  document.querySelectorAll('.filter').forEach((button) => {
    const selected = button.dataset.filter === filter;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', selected);
  });
}

document.querySelectorAll('.filter').forEach((button) => button.addEventListener('click', () => {
  filter = button.dataset.filter;
  setFilterButtons();
  render();
}));
$('#search').addEventListener('input', render);
$('#load-more').addEventListener('click', () => { limit = Math.min(200, limit + 50); refresh(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setupMovieSearch(refresh);
refresh();
