# Atualizações pelo painel

O botão **Baixar e aplicar atualizações** solicita uma atualização da branch
`main` de `threeebs/minecraft-servidor`. O painel recebe o pedido autenticado,
valida CSRF e grava uma tarefa fixa. Um serviço no Ubuntu executa o Git e o
Docker; o container PHP não recebe o socket Docker nem a chave SSH.

## Ativar uma vez no Ubuntu

Primeiro incorpore a PR do atualizador à `main`. No servidor:

```bash
cd ~/projeto/minecraft/minecraft-server
git fetch origin
git switch main
git pull --ff-only
sudo bash scripts/install-panel-updater.sh
```

O instalador verifica Git, Python 3, Docker Compose v2, acesso ao daemon Docker,
branch `main` e ausência de alterações locais. Ele utiliza o usuário que
executou `sudo`, com UID 1000 (o mesmo usado pelo painel atual).

Na primeira execução, cria uma chave SSH dedicada sem senha, acessível somente
ao usuário do Ubuntu. Se ela ainda não tem acesso ao repositório, mostra
**apenas a chave pública** e encerra antes de instalar o serviço.

Cadastre a chave em:

`threeebs/minecraft-servidor → Settings → Deploy keys → Add deploy key`

Nome sugerido: **StudioCraft painel**. Deixe **Allow write access desmarcado**.
Essa chave é de leitura de um único repositório. Não substitui sua chave pessoal
nem solicita sua senha SSH pelo navegador.

Depois repita o mesmo comando:

```bash
sudo bash scripts/install-panel-updater.sh
```

Se o instalador pedir a confirmação da identidade SSH do GitHub, use
`ssh -T git@github.com`, confirme a identidade pelos fingerprints oficiais
do GitHub e execute novamente. O instalador não aceita automaticamente uma
identidade desconhecida.

O serviço verifica a fila a cada cinco segundos. O instalador também reconstrói
o painel e inicia o restaurador. O login passa a usar um volume persistente;
na primeira instalação desse volume, entre novamente no painel.

## Usar

1. Faça login e clique em **Baixar e aplicar atualizações**.
2. Confirme que os serviços alterados podem reiniciar.
3. Acompanhe as etapas e a revisão instalada na seção **Atualizações do servidor**.

Durante a reconstrução do painel, a página pode ficar indisponível por alguns
segundos. Ela tenta consultar o progresso novamente. Se necessário, recarregue
e entre no painel; o progresso fica salvo no servidor.

O serviço recusa alterações locais, branch diferente de `main` e divergências
com o GitHub. Não faz `stash`, não força o Git e não descarta trabalho local.
Atualizações, backups e restaurações usam uma trava compartilhada.

A revisão é preparada em uma pasta temporária. As imagens são construídas com
tags isoladas antes de alterar o código instalado. O nome do projeto Docker
vem do container Minecraft ativo, evitando criar uma segunda instalação.
Somente serviços afetados são recriados; alterações nos arquivos Compose
podem afetar todos os serviços.

O serviço não edita `.env`, mundos ou backups. Arquivos desses diretórios no
Git remoto são recusados. Antes de recriar o Minecraft, solicita
`save-all flush` e permite 60 segundos para o encerramento.

Se a aplicação falhar, tenta recuperar o código e as imagens anteriores sem
descartar alterações concorrentes do operador. Essa recuperação não reverte
dados do jogo: faça um snapshot antes de atualizar a versão do Minecraft/mods.
Uma atualização que altere o formato do mundo pode exigir recuperação manual
do snapshot.

## Diagnóstico

```bash
systemctl status studiocraft-panel-updater.timer
sudo journalctl -u studiocraft-panel-updater.service -n 30 --no-pager
```

O painel mostra mensagens curtas, sem credenciais nem a saída bruta dos
comandos. O registro privado fica em
`~/.local/state/studiocraft-updater/last-command.log`, com permissão 600.

Se o Ubuntu desligar no meio de uma atualização, `update.working` permanece
como sinal de interrupção. O botão fica bloqueado para impedir uma repetição
incerta. Confira o estado do Git e dos containers antes de mover esse arquivo
para fora da pasta `minecraft-painel/jobs/` e solicitar uma nova atualização.

O botão aplica commits já publicados na `main`; ele não incorpora PRs, não
cria commits, não envia arquivos ao GitHub e não atualiza mods externos por
conta própria. Alterações nos arquivos do instalador ou na configuração do
systemd podem exigir executar novamente o instalador.

## Testes

```bash
python3 -m unittest discover -s tests -v
```

Os testes do atualizador usam repositórios Git locais e um Docker simulado.
Não acessam o servidor ou o mundo real. Para verificar a interface em Chromium,
instale Playwright e ative `RUN_BROWSER_TESTS=1`; se necessário, defina
`CHROMIUM_EXECUTABLE_PATH`.
