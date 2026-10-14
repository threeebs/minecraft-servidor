# Minecraft Mahal — Painel PHP + backup e restauração

Esta é uma **extensão** do seu projeto em `~/minecraft-server`, não uma substituição. O `compose.yaml` original e todo o conteúdo de `data/` são preservados. Instale os arquivos deste ZIP **dentro** de `~/minecraft-server`.

## O que faz

- Painel PHP 8.3 com senha, proteção CSRF, console RCON e comandos rápidos.
- Snapshot manual consistente do mundo enquanto o jogo está online: `save-off`, `save-all flush`, compactação dos diretórios do mundo (incluindo inventários), `save-on` mesmo após erro.
- Lista, download e restauração com um clique dos snapshots.
- Durante a restauração, um **worker separado** para o container Minecraft, extrai o snapshot e reinicia o servidor. O painel **não possui** acesso ao socket Docker; apenas o worker interno possui esse acesso.
- Antes da restauração, conserva o mundo mais recente em `data/.pre-restore-<id>` para recuperação emergencial.

**Aviso de segurança:** o worker tem acesso privilegiado ao Docker do host. O painel escuta em `0.0.0.0:25555` para acesso local e pela rede, com senha longa. Mantenha a porta na rede de administração. Evite expor o painel via Tunnel sem Cloudflare Access (controle de identidade). O modo offline do Minecraft (TLauncher) permite falsificação de nicknames; não confunda senha do painel com autenticação dos jogadores.

## 1. Extrair sem substituir arquivos existentes

Faça isso no **Ubuntu**, onde já existem `compose.yaml` e `data/`:

```bash
cd ~/minecraft-server
# Copie o ZIP para esta pasta e execute:
unzip -n minecraft-painel-mahal.zip
ls compose.yaml compose.panel.yaml minecraft-painel/panel/index.php
```

O ZIP não inclui `compose.yaml` nem `data/`: os seus permanecem intocados.

## 2. Preparar senhas e diretórios

```bash
cd ~/minecraft-server
mkdir -p minecraft-painel/backups minecraft-painel/jobs
sudo chown 1000:1000 minecraft-painel/backups minecraft-painel/jobs
sudo chmod 770 minecraft-painel/backups minecraft-painel/jobs
```

Adicione estas **duas variáveis** ao seu `.env` existente (não o substitua). Se não existir, crie-o com `nano .env`:

```dotenv
PANEL_PASSWORD=COLOQUE_UMA_SENHA_FORTE_COM_20_CARACTERES_OU_MAIS
MC_RCON_PASSWORD=COLOQUE_OUTRA_SENHA_LONGA_E_DIFERENTE
```

Senhas devem ser **diferentes**. O painel exige no mínimo 16 caracteres. Não compartilhe o `.env` e execute `chmod 600 .env`. Se sua senha contiver `#`, `$` ou aspas, verifique a sintaxe de escape do `.env` do Docker Compose; para facilitar, use letras, números e hífens.

O arquivo `compose.panel.yaml` ativa/define a senha RCON do container já existente. Não é necessário expor a porta 25575 no roteador ou no host.

## 3. Subir mantendo o mundo

```bash
cd ~/minecraft-server
# confira as mudanças combinadas antes de aplicar
docker compose -f compose.yaml -f compose.panel.yaml config --quiet

docker compose -f compose.yaml -f compose.panel.yaml up -d --build

docker compose -f compose.yaml -f compose.panel.yaml ps
```

**Não rode `docker compose down -v` e não apague `data/`.** A criação do painel poderá recriar o container Minecraft para aplicar a senha RCON; o bind mount `./data:/data` continua o mesmo, portanto preserva seu mundo. Seus serviços existentes mantêm as opções no `compose.yaml` original (Minecraft 26.2, Survival/Hardcore, 25565 etc.).

O `compose.panel.yaml` só é utilizado quando incluído com `-f`; para gerenciar painel e Minecraft daqui em diante, use os dois `-f` como mostrado acima.

## 4. Abrir o painel

No navegador do próprio Ubuntu: **http://localhost:25555**.

No Windows ou celular da mesma rede: **http://IP_DO_UBUNTU:25555**.
Use `hostname -I` no Ubuntu para descobrir os IPs disponíveis. Entre com `PANEL_PASSWORD`.

O bind padrão é `0.0.0.0`, que escuta em todas as interfaces. Esse endereço não é a URL do navegador.
Você pode ajustar `PANEL_BIND_ADDRESS` e `PANEL_PORT` no `.env`; os padrões são `0.0.0.0` e `25555`.

O terminal aceita comandos Minecraft e mostra as respostas sem recarregar a página.
O histórico da sessão guarda até 50 envios; use ↑ e ↓ para repetir comandos.
Consulte [README.md](README.md) para exemplos e atualização apenas do painel.

## 5. Seu primeiro backup, antes de jogar

No painel, clique **Criar snapshot agora**. Um arquivo `world-AAAAMMDD-HHMMSS-XXXXXX.tar.gz` aparecerá em `minecraft-painel/backups/`. Guarde uma cópia externa: se o disco Ubuntu falhar, snapshots mantidos nele também serão perdidos.

Para voltar ao último snapshot depois de morrer, acesse o painel → **Restaurar este backup**. Aguarde o status `CONCLUÍDO` e reconecte ao `minecraft.mahal.pro`. **Todo o progresso, os inventários e as mortes posteriores ao snapshot escolhido serão revertidos.** O servidor desconecta todos durante a restauração.

Ao restaurar, o mundo imediatamente anterior é guardado em `data/.pre-restore-<id>`. Depois de confirmar o sucesso e guardar outro backup, você pode remover as cópias de emergência antigas manualmente para liberar espaço. Cada snapshot adicional também ocupa disco.

## Logs e solução de problemas

```bash
cd ~/minecraft-server
docker compose -f compose.yaml -f compose.panel.yaml logs -f painel restaurador
# logs do Minecraft
docker compose -f compose.yaml -f compose.panel.yaml logs --tail=80 minecraft
# ver espaço livre
df -h .
```

Se o painel disser "RCON indisponível", espere a linha `Done ...` no log do Minecraft. Se disser senha incorreta, verifique `MC_RCON_PASSWORD` e recrie o container com `docker compose -f compose.yaml -f compose.panel.yaml up -d --force-recreate minecraft` (mundo preservado). Em caso de restauração interrompida, examine `data/.pre-restore-*` **antes de tentar novamente**.

**Limitação:** foi preparado com base na estrutura que você mostrou (serviço `minecraft`, container `minecraft-server`, mount `./data:/data`). Se seu `compose.yaml` real usa nomes ou caminhos diferentes, ajuste `compose.panel.yaml` antes de subir. O painel usa diretórios normais de Paper (`level-name` e dimensões `_nether`/`_the_end`). Mods com dimensões próprias exigem extensão do mecanismo de snapshot.
