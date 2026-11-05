import {api} from './api.js';
import {bytes, element} from './format.js';

export async function showSources(movie, selection, controls, message, onQueued) {
  message.classList.remove('error-text');
  message.textContent = 'Finding available qualities…';
  const params = new URLSearchParams({season: selection.season, episode: selection.episode});
  const result = await api(`/movies/${encodeURIComponent(movie.id)}/sources?${params}`);
  if (!result.sources.length) {
    message.textContent = 'No downloadable MP4 source is available for this selection.';
    return;
  }
  const label = element('label', 'sr-only', `Download quality for ${movie.title}`);
  const select = element('select', 'quality-select');
  select.id = `quality-${movie.id}`;
  label.htmlFor = select.id;
  for (const source of result.sources) {
    const option = element('option', '', `${source.quality} · ${bytes(source.size_bytes)}`);
    option.value = source.id;
    select.append(option);
  }
  const download = element('button', 'primary', selection.all_episodes ? 'Download season' : 'Download');
  download.type = 'button';
  download.setAttribute('aria-label', `Download ${movie.title}`);
  download.addEventListener('click', async () => {
    download.disabled = true;
    message.classList.remove('error-text');
    message.textContent = 'Adding to your queue…';
    try {
      const data = await api(`/movies/${encodeURIComponent(movie.id)}/download`, {
        method: 'POST', body: JSON.stringify({source_id: select.value, ...selection}),
      });
      message.textContent = `${data.downloads.length} download${data.downloads.length === 1 ? '' : 's'} added to your queue.`;
      await onQueued();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error-text');
    } finally {
      download.disabled = false;
    }
  });
  controls.replaceChildren(label, select, download);
  if (result.subtitles?.length) {
    const subtitleLabel = element('label', '', 'Subtitles');
    const subtitles = element('select', 'quality-select');
    subtitles.id = `subtitles-${movie.id}`;
    subtitleLabel.htmlFor = subtitles.id;
    for (const caption of result.subtitles) {
      const option = element('option', '', caption.name);
      option.value = caption.language;
      subtitles.append(option);
    }
    const link = element('a', 'secondary', 'Save subtitles');
    function subtitleLink() {
      link.href = `/api/movies/${encodeURIComponent(movie.id)}/subtitles/${encodeURIComponent(subtitles.value)}?${params}`;
    }
    subtitles.addEventListener('change', subtitleLink);
    subtitleLink();
    controls.append(subtitleLabel, subtitles, link);
  }
  message.textContent = selection.all_episodes ?
    'Each episode will use this quality. Unavailable episodes will show an error in the queue.' : '';
  select.focus();
}
