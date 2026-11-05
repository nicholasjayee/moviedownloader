import {api} from './api.js';
import {bytes, element} from './format.js';

export async function showSources(movie, selection, controls, message, onQueued, isCurrent = () => true, idSuffix = '') {
  message.classList.remove('error-text');
  message.textContent = 'Finding available qualities…';
  const params = new URLSearchParams({season: selection.season, episode: selection.episode});
  const result = await api(`/movies/${encodeURIComponent(movie.id)}/sources?${params}`);
  if (!isCurrent()) return;
  const multiple = selection.all_episodes || selection.episodes?.length > 1;
  if (!result.sources.length) {
    message.textContent = 'No downloadable MP4 source is available for this selection.';
    return;
  }
  const label = element('label', 'sr-only', `Download quality for ${movie.title}`);
  const select = element('select', 'quality-select');
  select.id = `quality-${movie.id}${idSuffix}`;
  label.htmlFor = select.id;
  for (const source of result.sources) {
    const option = element('option', '', `${source.quality} · ${bytes(source.size_bytes)}${multiple ? ' (preview)' : ''}`);
    option.value = source.id;
    select.append(option);
  }
  const labelText = selection.all_episodes ? 'Download entire season' :
    selection.episodes?.length > 1 ? `Download ${selection.episodes.length} episodes` : 'Download';
  const download = element('button', 'primary', labelText);
  download.type = 'button';
  download.setAttribute('aria-label', `${labelText} for ${movie.title}`);
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
    const subtitleLabel = element('label', '', multiple ? `Subtitles · Episode ${selection.episode}` : 'Subtitles');
    const subtitles = element('select', 'quality-select');
    subtitles.id = `subtitles-${movie.id}${idSuffix}`;
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
  message.textContent = multiple ?
    `Qualities and sizes shown are for episode ${selection.episode}. Selected episodes will use this quality; availability may vary.` : '';
  select.focus();
}
