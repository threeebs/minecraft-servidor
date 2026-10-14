# Servidor Minecraft • Mahal / StudioCraft

Servidor Fabric em Docker com painel PHP, terminal RCON, backups e restauração do mundo.

## Painel local e acesso pela rede

O painel escuta em **0.0.0.0:25555** por padrão:

- Na máquina do servidor: **http://localhost:25555**
- Em outro computador ou celular da mesma rede: **http://IP_DO_SERVIDOR:25555**

`0.0.0.0` é o endereço de bind; no navegador use localhost ou o IP real da máquina.
Para descobrir os IPs no Ubuntu, execute `hostname -I`.

O acesso usa a senha `PANEL_PASSWORD` do `.env`, com pelo menos 16 caracteres.
O terminal envia comandos administrativos ao Minecraft via RCON interno (`minecraft:25575`).

### Preparar e iniciar

Na pasta do repositório, preserve o seu `.env` existente. Se ainda não existir:

```bash
cp -n .env.example .env
nano .env
chmod 600 .env
```

Preencha `PANEL_PASSWORD` e `MC_RCON_PASSWORD` com senhas diferentes.
As opções `PANEL_BIND_ADDRESS=0.0.0.0` e `PANEL_PORT=25555` são opcionais.

```bash
mkdir -p minecraft-painel/backups minecraft-painel/jobs
sudo chown 1000:1000 minecraft-painel/backups minecraft-painel/jobs
sudo chmod 770 minecraft-painel/backups minecraft-painel/jobs

docker compose -f compose.yaml -f compose.panel.yaml config --quiet
docker compose -f compose.yaml -f compose.panel.yaml up -d --build
docker compose -f compose.yaml -f compose.panel.yaml ps
```

Se Minecraft e RCON já estão funcionando e você está apenas atualizando o painel:

```bash
docker compose -f compose.yaml -f compose.panel.yaml up -d --build --no-deps painel
```

Essa atualização do painel não exige reiniciar o Minecraft.

## Terminal

- Digite um comando e pressione **Enter** ou **Enviar comando**.
- As respostas aparecem no terminal sem recarregar a página.
- Use **↑ / ↓** para navegar pelos últimos comandos.
- O histórico guarda até 50 envios na sessão; sai junto com o logout.
- **Limpar tela** limpa a visualização; o histórico da sessão continua disponível.
- Atalhos: jogadores, dia, noite, sem chuva, pacífico e salvar mundo.
- Comandos que alteram permissões, removem entidades ou param o servidor pedem confirmação no navegador.

Exemplos:

```text
list
weather clear
difficulty peaceful
gamemode creative Marvingames
time set day
save-all flush
```

Uma barra inicial é aceita. Envie um comando por vez, com até 256 bytes.
O terminal mostra as respostas aos comandos enviados; não acompanha os logs gerais do jogo.
Para acompanhar os logs:

```bash
docker compose -f compose.yaml -f compose.panel.yaml logs -f --tail=100 minecraft
```

Se a conexão falhar depois de um envio, confira o estado do servidor antes de repetir:
o comando pode já ter sido executado.

## Operação

```bash
# Reiniciar apenas o jogo
docker compose -f compose.yaml -f compose.panel.yaml restart minecraft

# Logs do painel e do restaurador
docker compose -f compose.yaml -f compose.panel.yaml logs -f painel restaurador

# Parar os serviços
docker compose -f compose.yaml -f compose.panel.yaml down
```

Os mundos ficam em `data/`. Backups ficam em `minecraft-painel/backups/`.
Veja [LEIA-ME.md](LEIA-ME.md) para detalhes de backup e restauração.

O RCON não publica uma porta no host. O bind `0.0.0.0` disponibiliza o painel
em todas as interfaces da máquina; mantenha esse acesso na rede de administração.

## Validação local

Os testes usam um RCON simulado, sem acessar o servidor real. Requerem PHP 8.3+ e Python 3:

```bash
python3 -m unittest discover -s tests -v
```

Se PHP não estiver no PATH, informe o caminho em `PHP_BINARY`.
