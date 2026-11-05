import {api} from './api.js';
import {element} from './format.js';

export function watchPlayer(details) {
  const movie = details.movie;
  const section = element('section', 'watch-section');
  section.setAttribute('aria-label', 'Watch online');
  section.append(element('h3', '', movie.kind === 'series' ? 'Watch an episode' : 'Watch movie'));
  const selectors = element('div', 'watch-selectors');
  const message = element('p', 'movie-message');
  message.setAttribute('role', 'status');
  const video = element('video', 'preview-video watch-video');
  video.controls = true;
  video.playsInline = true;
  video.preload = 'metadata';
  video.hidden = true;
  video.setAttribute('aria-label', `${movie.title} player`);
  const qualityLabel = element('label', 'watch-quality', 'Quality');
  const quality = element('select', 'quality-select');
  quality.setAttribute('aria-label', 'Playback quality');
  qualityLabel.append(quality);
  qualityLabel.hidden = true;
  const watch = element('button', 'primary', movie.kind === 'series' ? 'Watch episode' : 'Watch movie');
  watch.type = 'button';
  let season = 0;
  let episode = 0;
  let controller;
  let version = 0;
  let disposed = false;
  let hasPlayed = false;

  function stop() {
    version++;
    controller?.abort();
    video.pause();
    video.removeAttribute('src');
    video.onloadedmetadata = null;
    video.load();
    video.hidden = true;
    qualityLabel.hidden = true;
    quality.replaceChildren();
    message.textContent = '';
    watch.disabled = false;
    hasPlayed = false;
  }

  if (movie.kind === 'series' && details.seasons.length) {
    const seasonLabel = element('label', '', 'Season');
    const seasonSelect = element('select', 'quality-select');
    seasonSelect.setAttribute('aria-label', 'Watch season');
    details.seasons.forEach((item) => {
      const option = element('option', '', `Season ${item.number}`);
      option.value = item.number;
      seasonSelect.append(option);
    });
    const episodeLabel = element('label', '', 'Episode');
    const episodeSelect = element('select', 'quality-select');
    episodeSelect.setAttribute('aria-label', 'Watch episode');
    function selectSeason() {
      stop();
      season = Number(seasonSelect.value);
      const selected = details.seasons.find((item) => item.number === season);
      episodeSelect.replaceChildren();
      for (let number = 1; number <= selected.episodes; number++) {
        const option = element('option', '', `Episode ${number}`);
        option.value = number;
        episodeSelect.append(option);
      }
      episode = 1;
    }
    seasonSelect.addEventListener('change', selectSeason);
    episodeSelect.addEventListener('change', () => {
      stop();
      episode = Number(episodeSelect.value);
    });
    seasonLabel.append(seasonSelect);
    episodeLabel.append(episodeSelect);
    selectors.append(seasonLabel, episodeLabel);
    selectSeason();
  }

  function playSource(autoplay = true, position = 0) {
    const current = ++version;
    video.pause();
    video.onloadedmetadata = () => {
      if (disposed || current !== version) return;
      if (position > 0 && Number.isFinite(video.duration)) {
        video.currentTime = Math.min(position, Math.max(0, video.duration - .1));
      }
      if (!autoplay) message.textContent = 'Ready. Press play to watch.';
      if (autoplay) video.play().catch((error) => {
        if (disposed || current !== version || error.name === 'AbortError') return;
        message.textContent = error.name === 'NotAllowedError' ?
          'Press play in the player to start watching.' :
          'This source could not be played. Try another quality or episode.';
      });
    };
    const params = new URLSearchParams({season, episode, source_id: quality.value});
    video.src = `/api/movies/${encodeURIComponent(movie.id)}/watch?${params}`;
    video.hidden = false;
    video.scrollIntoView({block: 'nearest', behavior: 'auto'});
    message.classList.remove('error-text');
    message.textContent = 'Opening video…';
    video.load();
  }

  watch.addEventListener('click', async () => {
    stop();
    const requestVersion = version;
    const requestController = new AbortController();
    controller = requestController;
    watch.disabled = true;
    message.classList.remove('error-text');
    message.textContent = 'Finding playback qualities…';
    try {
      const params = new URLSearchParams({season, episode});
      const result = await api(`/movies/${encodeURIComponent(movie.id)}/sources?${params}`, {signal: requestController.signal});
      if (disposed || version !== requestVersion) return;
      if (!result.sources.length) {
        message.textContent = 'No playable video is available for this selection.';
        return;
      }
      for (const source of result.sources) {
        const option = element('option', '', source.quality);
        option.value = source.id;
        quality.append(option);
      }
      const preferred = result.sources.find((source) => source.quality === '720p') || result.sources[0];
      quality.value = preferred.id;
      qualityLabel.hidden = false;
      playSource();
    } catch (error) {
      if (disposed || error.name === 'AbortError' || version !== requestVersion) return;
      message.textContent = error.message;
      message.classList.add('error-text');
    } finally {
      if (!disposed && controller === requestController) watch.disabled = false;
    }
  });
  quality.addEventListener('change', () => playSource(!video.paused || !hasPlayed, video.currentTime));
  video.addEventListener('playing', () => { hasPlayed = true; message.textContent = ''; });
  video.addEventListener('error', () => {
    if (!disposed && video.hasAttribute('src')) {
      message.textContent = 'This source could not be played. Try another quality or episode.';
      message.classList.add('error-text');
    }
  });
  section.append(selectors, watch, qualityLabel, message, video,
    element('p', 'hint', 'Watch here, or use the download controls to keep a copy on the server.'));
  return {element: section, dispose() { disposed = true; stop(); }};
}
