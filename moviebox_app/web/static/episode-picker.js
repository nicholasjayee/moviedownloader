import {element} from './format.js';

export function episodePicker(movie, seasons, choose) {
  const picker = element('div', 'episode-picker');
  const seasonLabel = element('label', '', 'Season');
  const seasonSelect = element('select', 'quality-select');
  seasonSelect.id = `season-${movie.id}`;
  seasonLabel.htmlFor = seasonSelect.id;
  for (const season of seasons) {
    const option = element('option', '', `Season ${season.number} · ${season.episodes} episodes`);
    option.value = season.number;
    seasonSelect.append(option);
  }
  const episodeLabel = element('label', '', 'Episode');
  const episodeSelect = element('select', 'quality-select');
  episodeSelect.id = `episode-${movie.id}`;
  episodeLabel.htmlFor = episodeSelect.id;
  function episodes() {
    const season = seasons.find((item) => item.number === Number(seasonSelect.value));
    episodeSelect.replaceChildren();
    const all = element('option', '', 'All episodes in this season');
    all.value = 'all';
    episodeSelect.append(all);
    for (let number = 1; number <= season.episodes; number++) {
      const option = element('option', '', `Episode ${number}`);
      option.value = number;
      episodeSelect.append(option);
    }
    episodeSelect.value = '1';
  }
  const button = element('button', 'secondary', 'Choose quality');
  button.type = 'button';
  const output = element('div', 'movie-controls');
  seasonSelect.addEventListener('change', () => { episodes(); output.replaceChildren(); });
  episodeSelect.addEventListener('change', () => output.replaceChildren());
  button.addEventListener('click', async () => {
    button.disabled = true;
    const selection = {
      season: Number(seasonSelect.value),
      episode: episodeSelect.value === 'all' ? 1 : Number(episodeSelect.value),
      all_episodes: episodeSelect.value === 'all',
    };
    try { await choose(selection, output); }
    finally { button.disabled = false; }
  });
  episodes();
  picker.append(seasonLabel, seasonSelect, episodeLabel, episodeSelect, button, output);
  return picker;
}
