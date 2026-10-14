(() => {
  'use strict';
  const form = document.querySelector('#console-form');
  if (!form) return;
  const input = form.elements.command;
  const output = document.querySelector('#console-output');
  const state = document.querySelector('#console-state');
  const controls = [...document.querySelectorAll('[data-command], #console-form button')];
  let busy = false;
  let history = [];
  let cursor = 0;
  let draft = '';
  const entries = [...output.querySelectorAll('.console-entry')];
  history = entries.map(entry => entry.dataset.commandText).slice(-50);
  cursor = history.length;
  if (!entries.length) output.textContent = 'O console está pronto. Envie um comando abaixo.';
  output.scrollTop = output.scrollHeight;
  const quickForms = [...document.querySelectorAll('[data-quick-command]')];
  const sensitive = /^(stop|op|deop|ban|ban-ip|pardon|pardon-ip|kick|kill|reload|save-off|whitelist|fill|clone|setblock)\b/i;

  function append(command, response, error = false) {
    if (!entries.length) output.replaceChildren();
    const entry = document.createElement('div');
    entry.className = 'console-entry' + (error ? ' console-error' : '');
    const prompt = document.createElement('div');
    prompt.className = 'console-prompt';
    const time = new Date().toLocaleTimeString('pt-BR');
    prompt.textContent = '[' + time + '] > ' + command;
    const text = document.createElement('div');
    text.className = 'console-response';
    text.textContent = response;
    entry.append(prompt, text);
    output.append(entry);
    entries.push(entry);
    if (entries.length > 50) entries.shift().remove();
    output.scrollTop = output.scrollHeight;
  }

  async function execute(value) {
    if (busy) return;
    const command = value.trim().replace(/^\/+/, '');
    if (!command) return;
    if (sensitive.test(command) && !confirm('Executar como administrador: ' + command + '?')) return;
    busy = true;
    controls.forEach(control => { control.disabled = true; });
    state.textContent = 'Executando…';
    history = [...history.filter(item => item !== command), command].slice(-50);
    cursor = history.length;
    draft = '';
    input.value = '';
    try {
      const body = new URLSearchParams({action: 'command', format: 'json', csrf: form.elements.csrf.value, command});
      const result = await fetch(new URL(form.getAttribute('action') || '/', document.baseURI), {method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}});
      const data = await result.json();
      append(command, data.response || data.error || '(Sem mensagem de retorno)', !result.ok);
      if (data.player_status !== undefined) document.querySelector('#player-status').textContent = data.player_status;
      state.textContent = result.ok ? 'Pronto para o próximo comando' : 'Falha no envio';
      if (result.status === 401) state.textContent = 'Sessão encerrada. Atualize a página e entre novamente.';
    } catch {
      append(command, 'Conexão com o painel interrompida. O comando pode ter sido executado; confira o servidor antes de repetir.', true);
      state.textContent = 'Falha de conexão';
    } finally {
      busy = false;
      controls.forEach(control => { control.disabled = false; });
      input.focus();
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    execute(input.value);
  });
  quickForms.forEach(quick => quick.addEventListener('submit', event => {
    event.preventDefault();
    execute(quick.elements.command.value);
  }));
  input.addEventListener('keydown', event => {
    if (!['ArrowUp', 'ArrowDown'].includes(event.key) || !history.length) return;
    event.preventDefault();
    if (cursor === history.length) draft = input.value;
    cursor = Math.max(0, Math.min(history.length, cursor + (event.key === 'ArrowUp' ? -1 : 1)));
    input.value = cursor === history.length ? draft : history[cursor];
  });
  document.querySelector('#clear-console').addEventListener('click', () => {
    output.textContent = 'O console está pronto. Envie um comando abaixo.';
    entries.length = 0;
    state.textContent = 'Console limpo';
  });
})();
