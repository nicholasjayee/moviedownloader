import {element} from './format.js';

export function episodePicker(movie, seasons, choose, onChange = () => {}, idSuffix = '') {
  const picker = element('div', 'episode-picker');
  const seasonLabel = element('label', '', 'Season');
  const seasonSelect = element('select', 'quality-select');
  seasonSelect.id = `season-${movie.id}${idSuffix}`;
  seasonLabel.htmlFor = seasonSelect.id;
  for (const season of seasons) {
    const option = element('option', '', `Season ${season.number} · ${season.episodes} episodes`);
    option.value = season.number;
    seasonSelect.append(option);
  }
  const fieldset = element('fieldset', 'episode-selection');
  const legend = element('legend', '', 'Episodes');
  const grid = element('div', 'episode-grid');
  const actions = element('div', 'episode-selection-actions');
  const selectAll = element('button', 'secondary', 'Select all');
  const clear = element('button', 'secondary', 'Clear');
  selectAll.type = clear.type = 'button';
  actions.append(selectAll, clear);
  fieldset.append(legend, actions, grid);
  const count = element('p', 'episode-count');
  count.setAttribute('role', 'status');
  count.setAttribute('aria-live', 'polite');
  const button = element('button', 'secondary', 'Choose quality');
  button.type = 'button';
  const output = element('div', 'movie-controls');
  let selected = new Set();
  let revision = 0;

  function update() {
    revision++;
    const total = grid.children.length;
    count.textContent = selected.size === total ? `All ${total} episodes selected` :
      `${selected.size} episode${selected.size === 1 ? '' : 's'} selected`;
    button.disabled = selected.size === 0;
    selectAll.disabled = selected.size === total;
    clear.disabled = selected.size === 0;
    output.replaceChildren();
    onChange();
  }

  function episodes() {
    const season = seasons.find((item) => item.number === Number(seasonSelect.value));
    grid.replaceChildren();
    selected = new Set([1]);
    for (let number = 1; number <= season.episodes; number++) {
      const label = element('label', 'episode-option');
      const input = element('input');
      input.type = 'checkbox';
      input.value = number;
      input.checked = number === 1;
      input.setAttribute('aria-label', `Episode ${number}`);
      input.addEventListener('change', () => {
        if (input.checked) selected.add(number);
        else selected.delete(number);
        update();
      });
      label.append(input, document.createTextNode(String(number)));
      grid.append(label);
    }
    update();
  }

  function toggleAll(checked) {
    selected.clear();
    grid.querySelectorAll('input').forEach((input) => {
      input.checked = checked;
      if (checked) selected.add(Number(input.value));
    });
    update();
  }
  selectAll.addEventListener('click', () => toggleAll(true));
  clear.addEventListener('click', () => toggleAll(false));
  seasonSelect.addEventListener('change', episodes);
  button.addEventListener('click', async () => {
    if (!selected.size) return;
    button.disabled = true;
    const requestRevision = revision;
    const numbers = [...selected].sort((a, b) => a - b);
    const all = numbers.length === grid.children.length;
    const selection = {
      season: Number(seasonSelect.value),
      episode: numbers[0],
      all_episodes: all,
      ...(all ? {} : {episodes: numbers}),
    };
    try {
      await choose(selection, output, () => revision === requestRevision);
    } finally {
      if (revision === requestRevision) button.disabled = false;
    }
  });
  episodes();
  picker.append(seasonLabel, seasonSelect, fieldset, count, button, output);
  return picker;
}
