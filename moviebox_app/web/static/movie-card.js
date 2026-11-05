import {api} from './api.js';
import {element} from './format.js';
import {episodePicker} from './episode-picker.js';
import {showSources} from './source-picker.js';

export function movieCard(movie, onQueued) {
  const card = element('article', 'movie-card');
  const poster = element('div', 'movie-poster');
  if (movie.poster.startsWith('https://')) {
    const image = element('img');
    image.src = movie.poster;
    image.alt = '';
    image.loading = 'lazy';
    image.addEventListener('error', () => image.remove());
    poster.append(image);
  }
  card.append(poster);
  const content = element('div', 'movie-card-body');
  content.append(element('h3', '', movie.title));
  const details = [movie.kind === 'series' ? 'Series' : 'Movie', movie.year,
    movie.rating ? `IMDb ${movie.rating}` : ''].filter(Boolean);
  content.append(element('p', 'movie-meta', details.join(' · ')));
  if (movie.genres) content.append(element('p', 'movie-genres', movie.genres));
  const controls = element('div', 'movie-controls');
  const choose = element('button', 'secondary', movie.kind === 'series' ? 'Choose episode' : 'Choose quality');
  choose.type = 'button';
  choose.setAttribute('aria-label', `Choose quality for ${movie.title}`);
  const message = element('p', 'movie-message');
  message.setAttribute('role', 'status');
  async function sources(selection, output) {
    try { await showSources(movie, selection, output, message, onQueued); }
    catch (error) {
      message.textContent = error.message;
      message.classList.add('error-text');
    }
  }
  choose.addEventListener('click', async () => {
    choose.disabled = true;
    choose.textContent = 'Finding sources…';
    message.textContent = '';
    try {
      const result = await api(`/movies/${encodeURIComponent(movie.id)}/details`);
      if (result.movie.kind === 'series') {
        controls.replaceChildren(episodePicker(movie, result.seasons, sources));
        message.textContent = 'Choose a season and episode, then a quality.';
      } else {
        await sources({season: 0, episode: 0, all_episodes: false}, controls);
      }
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error-text');
      choose.textContent = 'Try again';
    } finally {
      choose.disabled = false;
    }
  });
  controls.append(choose);
  content.append(controls, message);
  card.append(content);
  return card;
}
