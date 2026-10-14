(() => {
  'use strict';
  const form = document.querySelector('#update-form');
  if (!form) return;
  const button = form.querySelector('button');
  const message = document.querySelector('#update-message');
  const revision = document.querySelector('#update-revision');
  const log = document.querySelector('#update-log');
  let sending = false;
  let busy = form.dataset.busy === '1';
  let failures = 0;
  let timer;
  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(poll, delay);
  }
  function render(data) {
    busy = Boolean(data.busy);
    button.disabled = sending || !data.can_update;
    button.textContent = busy ? 'Atualização em andamento…' : 'Baixar e aplicar atualizações';
    message.textContent = data.message;
    revision.textContent = data.current ? 'Versão instalada: ' + data.current.slice(0, 12) : '';
    log.textContent = (data.events || []).map(event => event.time + ' · ' + event.message).join('\n');
  }
  async function poll() {
    try {
      const response = await fetch('/?update_status=1', {credentials: 'same-origin', cache: 'no-store'});
      if (response.status === 401) {
        button.disabled = true;
        message.textContent = 'Entre novamente no painel para acompanhar a atualização.';
        return;
      }
      if (!response.ok) throw new Error('status');
      render(await response.json());
      failures = 0;
    } catch {
      failures++;
      button.disabled = true;
      message.textContent = 'Aguardando o painel responder. Ele pode estar reiniciando durante a atualização.';
    }
    schedule(busy || failures ? 3000 : 10000);
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (sending || busy || button.disabled) return;
    if (!confirm('Baixar e aplicar as atualizações da main? Os serviços alterados podem reiniciar e desconectar jogadores.')) return;
    sending = true;
    button.disabled = true;
    message.textContent = 'Enviando pedido de atualização…';
    try {
      const body = new URLSearchParams({action: 'update', format: 'json', csrf: form.elements.csrf.value});
      const response = await fetch(new URL(form.getAttribute('action') || '/', document.baseURI), {
        method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'},
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Não foi possível solicitar a atualização.');
      sending = false;
      render(data);
      schedule(1000);
    } catch (error) {
      message.textContent = error.message || 'Confira o estado da atualização antes de repetir o pedido.';
    } finally { sending = false; }
  });
  poll();
})();
