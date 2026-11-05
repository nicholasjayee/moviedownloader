import {element} from './format.js';
import {downloadActions} from './download-actions.js';
import {openMoviePreview} from './movie-preview.js';

export function movieCard(movie, onQueued) {
  const card = element('article', 'movie-card');
  const poster = element('button', 'movie-poster');
  poster.type = 'button';
  poster.setAttribute('aria-label', `Preview ${movie.title}`);
  poster.setAttribute('aria-haspopup', 'dialog');
  poster.addEventListener('click', () => openMoviePreview(movie, onQueued, poster));
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
  const heading = element('h3');
  const title = element('button', 'movie-title-button', movie.title);
  title.type = 'button';
  title.setAttribute('aria-haspopup', 'dialog');
  title.addEventListener('click', () => openMoviePreview(movie, onQueued, title));
  heading.append(title);
  content.append(heading);
  const details = [movie.kind === 'series' ? 'Series' : 'Movie', movie.year,
    movie.rating ? `IMDb ${movie.rating}` : ''].filter(Boolean);
  content.append(element('p', 'movie-meta', details.join(' · ')));
  if (movie.genres) content.append(element('p', 'movie-genres', movie.genres));
  const preview = element('button', 'secondary preview-button', 'Preview');
  preview.type = 'button';
  preview.setAttribute('aria-label', `View details for ${movie.title}`);
  preview.setAttribute('aria-haspopup', 'dialog');
  preview.addEventListener('click', () => openMoviePreview(movie, onQueued, preview));
  content.append(preview, downloadActions(movie, onQueued));
  card.append(content);
  return card;
}
