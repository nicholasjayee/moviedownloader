import {api} from './api.js';
import {element} from './format.js';
import {episodePicker} from './episode-picker.js';
import {showSources} from './source-picker.js';

let nextId = 0;

export function downloadActions(movie, onQueued, details = null) {
  const idSuffix = `-actions-${++nextId}`;
  const panel = element('div', 'download-actions');
  const controls = element('div', 'movie-controls');
  const choose = element('button', 'secondary', movie.kind === 'series' ? 'Choose episodes' : 'Choose quality');
  choose.type = 'button';
  choose.setAttribute('aria-label', `Choose quality for ${movie.title}`);
  const message = element('p', 'movie-message');
  message.setAttribute('role', 'status');
  async function sources(selection, output, isCurrent = () => true) {
    const valid = () => panel.isConnected && isCurrent();
    try {
      await showSources(movie, selection, output, message, onQueued, valid, idSuffix);
    } catch (error) {
      if (!valid()) return;
      message.textContent = error.message;
      message.classList.add('error-text');
    }
  }
  choose.addEventListener('click', async () => {
    choose.disabled = true;
    choose.textContent = 'Loading…';
    message.textContent = '';
    message.classList.remove('error-text');
    try {
      const result = details || await api(`/movies/${encodeURIComponent(movie.id)}/details`);
      if (!panel.isConnected) return;
      movie = result.movie;
      if (movie.kind === 'series') {
        controls.replaceChildren(episodePicker(movie, result.seasons, sources, () => {
          message.textContent = '';
        }, idSuffix));
        message.textContent = 'Select episodes, or select all for the entire season.';
      } else {
        await sources({season: 0, episode: 0, all_episodes: false}, controls);
        if (choose.isConnected) choose.textContent = 'Check again';
      }
    } catch (error) {
      if (!panel.isConnected) return;
      message.textContent = error.message;
      message.classList.add('error-text');
      choose.textContent = 'Try again';
    } finally {
      choose.disabled = false;
    }
  });
  controls.append(choose);
  panel.append(controls, message);
  return panel;
}
