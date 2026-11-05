import {api} from './api.js';
import {element} from './format.js';
import {downloadActions} from './download-actions.js';
import {watchPlayer} from './watch-player.js';

let current = null;

function posterImage(movie) {
  const poster = element('div', 'preview-poster');
  if (movie.poster?.startsWith('https://')) {
    const image = element('img');
    image.src = movie.poster;
    image.alt = `${movie.title} poster`;
    image.addEventListener('error', () => image.remove());
    poster.append(image);
  }
  return poster;
}

function renderDetails(details, onQueued) {
  const movie = details.movie;
  const layout = element('div', 'preview-layout');
  layout.append(posterImage(movie));
  const information = element('div', 'preview-information');
  const metadata = [movie.kind === 'series' ? 'Series' : 'Movie', movie.year,
    movie.rating ? `IMDb ${movie.rating}` : '', details.country].filter(Boolean);
  information.append(element('p', 'preview-metadata', metadata.join(' · ')));
  if (movie.genres) information.append(element('p', 'preview-genres', movie.genres));
  information.append(element('h3', '', 'Synopsis'));
  information.append(element('p', 'preview-synopsis', details.description || 'No synopsis is available for this title.'));
  if (details.cast?.length) {
    const cast = element('p', 'preview-cast');
    cast.append(element('strong', '', 'Cast: '), document.createTextNode(details.cast.join(', ')));
    information.append(cast);
  }
  if (details.seasons?.length) {
    const episodes = details.seasons.reduce((total, season) => total + season.episodes, 0);
    information.append(element('p', 'preview-seasons',
      `${details.seasons.length} season${details.seasons.length === 1 ? '' : 's'} · ${episodes} episodes listed`));
  }
  const player = watchPlayer(details);
  information.append(player.element);
  const download = element('section', 'preview-download');
  download.setAttribute('aria-label', 'Download selection');
  download.append(element('h3', '', movie.kind === 'series' ? 'Choose episodes to download' : 'Download movie'),
    downloadActions(movie, onQueued, details));
  information.append(download);
  layout.append(information);
  const content = element('div');
  content.append(layout);
  const trailer = element('section', 'preview-trailer');
  trailer.setAttribute('aria-label', 'Trailer');
  trailer.append(element('h3', '', 'Trailer'));
  if (details.trailer?.url?.startsWith('https://')) {
    const video = element('video', 'preview-video');
    video.controls = true;
    video.playsInline = true;
    video.preload = 'none';
    video.src = details.trailer.url;
    video.setAttribute('aria-label', `${movie.title} trailer`);
    if (details.trailer.poster?.startsWith('https://')) video.poster = details.trailer.poster;
    const error = element('p', 'movie-message error-text', 'This trailer could not be played.');
    error.hidden = true;
    error.setAttribute('role', 'status');
    video.addEventListener('error', () => { error.hidden = false; });
    trailer.append(video, error);
  } else {
    trailer.append(element('p', 'movie-message', 'No trailer is available for this title.'));
  }
  content.append(trailer);
  return {element: content, dispose: player.dispose};
}

export function openMoviePreview(movie, onQueued, trigger = document.activeElement) {
  current?.dispose();
  const dialog = element('dialog', 'movie-preview');
  dialog.setAttribute('aria-labelledby', 'preview-title');
  const header = element('header', 'preview-header');
  const heading = element('h2', '', movie.title);
  heading.id = 'preview-title';
  const close = element('button', 'preview-close', 'Close ×');
  close.type = 'button';
  close.autofocus = true;
  close.setAttribute('aria-label', 'Close preview');
  header.append(heading, close);
  const body = element('div', 'preview-body');
  dialog.append(header, body);
  const controller = new AbortController();
  let disposed = false;
  let disposeContent = () => {};
  const state = {dispose};

  function dispose() {
    if (disposed) return;
    disposed = true;
    controller.abort();
    disposeContent();
    dialog.querySelectorAll('video').forEach((video) => {
      video.pause();
      video.removeAttribute('src');
      video.load();
    });
    dialog.close();
    dialog.remove();
    if (current === state) {
      current = null;
      document.body.classList.remove('preview-open');
      if (trigger?.isConnected) trigger.focus({preventScroll: true});
    }
  }

  async function load() {
    body.setAttribute('aria-busy', 'true');
    const loading = element('p', 'preview-loading', 'Loading title details…');
    loading.setAttribute('role', 'status');
    body.replaceChildren(loading);
    try {
      const details = await api(`/movies/${encodeURIComponent(movie.id)}/details`, {signal: controller.signal});
      if (disposed) return;
      heading.textContent = details.movie.title;
      const content = renderDetails(details, onQueued);
      disposeContent = content.dispose;
      body.replaceChildren(content.element);
    } catch (error) {
      if (disposed || error.name === 'AbortError') return;
      const message = element('p', 'error', error.message);
      message.setAttribute('role', 'alert');
      const retry = element('button', 'secondary', 'Try again');
      retry.type = 'button';
      retry.addEventListener('click', load);
      body.replaceChildren(message, retry);
    } finally {
      if (!disposed) body.setAttribute('aria-busy', 'false');
    }
  }

  close.addEventListener('click', dispose);
  dialog.addEventListener('play', (event) => {
    dialog.querySelectorAll('video').forEach((video) => {
      if (video !== event.target) video.pause();
    });
  }, true);
  dialog.addEventListener('close', dispose);
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) dispose();
  });
  current = state;
  document.body.append(dialog);
  document.body.classList.add('preview-open');
  dialog.showModal();
  load();
}
