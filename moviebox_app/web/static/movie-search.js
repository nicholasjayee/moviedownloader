import {api} from './api.js';
import {movieCard} from './movie-card.js';

export function setupMovieSearch(onQueued) {
  const form = document.querySelector('#movie-search-form');
  const query = document.querySelector('#movie-query');
  const submit = document.querySelector('#movie-search-submit');
  const results = document.querySelector('#movie-results');
  const status = document.querySelector('#movie-search-status');
  const error = document.querySelector('#movie-search-error');
  const more = document.querySelector('#more-movies');
  let currentQuery = '';
  let page = 1;
  let controller;
  let version = 0;

  async function search(append = false) {
    const text = append ? currentQuery : query.value.trim();
    if (!text) return;
    controller?.abort();
    controller = new AbortController();
    const requestVersion = ++version;
    const nextPage = append ? page + 1 : 1;
    if (!append) results.replaceChildren();
    more.hidden = true;
    submit.disabled = true;
    more.disabled = true;
    error.hidden = true;
    status.textContent = 'Searching Moviebox…';
    results.setAttribute('aria-busy', 'true');
    try {
      const params = new URLSearchParams({q: text, page: nextPage});
      const data = await api(`/movies/search?${params}`, {signal: controller.signal});
      if (requestVersion !== version) return;
      currentQuery = text;
      page = nextPage;
      for (const movie of data.movies) results.append(movieCard(movie, onQueued));
      status.textContent = results.children.length ?
        `${results.children.length} movies found for “${text}”.` :
        `No movies found for “${text}”. Try another title.`;
      more.hidden = !data.has_more;
    } catch (failure) {
      if (failure.name === 'AbortError' || requestVersion !== version) return;
      status.textContent = '';
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      if (requestVersion === version) {
        submit.disabled = false;
        more.disabled = false;
        results.setAttribute('aria-busy', 'false');
      }
    }
  }

  form.addEventListener('submit', (event) => { event.preventDefault(); search(); });
  more.addEventListener('click', () => search(true));
}
