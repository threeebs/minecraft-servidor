#!/usr/bin/env bash
# Instala uma vez o consumidor da fila no host Ubuntu, fora do container PHP.
set -euo pipefail

if [[ ${EUID} -ne 0 || -z ${SUDO_USER:-} || ${SUDO_USER} == root ]]; then
  echo 'Execute como seu usuário do servidor: sudo bash scripts/install-panel-updater.sh'
  exit 1
fi
repo=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
operator=$SUDO_USER
operator_home=$(getent passwd "$operator" | cut -d: -f6)
key="$operator_home/.ssh/studiocraft-updater_ed25519"
state="$operator_home/.local/state/studiocraft-updater"
jobs="$repo/minecraft-painel/jobs"
unit=studiocraft-panel-updater

# Paths in systemd directives are intentionally limited to ordinary Linux paths.
for path in "$repo" "$operator_home"; do
  if [[ ! $path =~ ^/[A-Za-z0-9_./-]+$ ]]; then
    echo 'Use um caminho sem espaços ou caracteres especiais para instalar o atualizador.'
    exit 1
  fi
done
if [[ $(id -u "$operator") -ne 1000 || $(stat -c %U "$repo/.git") != "$operator" ]]; then
  echo 'O repositório deve pertencer ao usuário UID 1000, o mesmo usado pelo painel.'
  exit 1
fi
for tool in git python3 docker systemctl ssh ssh-keygen; do
  command -v "$tool" >/dev/null || { echo "Instale o comando necessário: $tool"; exit 1; }
done
as_operator() { runuser -u "$operator" -- "$@"; }
if [[ $(as_operator git -C "$repo" branch --show-current) != main ]]; then
  echo 'Incorpore a PR, execute git switch main e git pull --ff-only antes da instalação.'
  exit 1
fi
if [[ -n $(as_operator git -C "$repo" status --porcelain) ]]; then
  echo 'Existem alterações locais no repositório. Salve-as no Git antes da instalação.'
  exit 1
fi
[[ -f $repo/.env ]] || { echo 'Configure primeiro o .env do Minecraft e do painel.'; exit 1; }
as_operator docker compose version >/dev/null
as_operator docker info >/dev/null
install -d -m 700 -o "$operator" -g "$operator" "$operator_home/.ssh" "$state"
if [[ ! -f $key ]]; then
  as_operator ssh-keygen -q -t ed25519 -N '' -C studiocraft-updater -f "$key"
fi
chmod 600 "$key"
if ! as_operator ssh-keygen -F github.com -f "$operator_home/.ssh/known_hosts" >/dev/null 2>&1; then
  echo 'Confirme primeiro a identidade SSH do GitHub com ssh -T git@github.com e execute novamente.'
  exit 1
fi
ssh_command="ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10"
if ! as_operator env GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$ssh_command" \
    git ls-remote --exit-code git@github.com:threeebs/minecraft-servidor.git refs/heads/main \
    >"$state/access-check.log" 2>&1; then
  chmod 600 "$state/access-check.log"
  echo 'Cadastre esta chave pública em threeebs/minecraft-servidor → Settings → Deploy keys → Add deploy key.'
  echo 'Nome: StudioCraft painel. Deixe Allow write access DESMARCADO.'
  cat "$key.pub"
  echo 'Depois execute novamente: sudo bash scripts/install-panel-updater.sh'
  exit 2
fi
rm -f "$state/access-check.log"
install -d -m 770 -o "$operator" -g "$operator" "$jobs" "$repo/minecraft-painel/backups"
if compgen -G "$jobs/restore-*.job" >/dev/null || compgen -G "$jobs/restore-*.working" >/dev/null ||
   [[ -e $jobs/backup-in-progress || -e $jobs/update.working || -e $jobs/update.job ]]; then
  echo 'Existe uma operação pendente. Aguarde a conclusão antes da instalação.'
  exit 1
fi
cat >"/etc/systemd/system/$unit.service" <<EOF
[Unit]
Description=StudioCraft - atualizações solicitadas pelo painel
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
User=$operator
Group=$operator
WorkingDirectory=$repo
Environment=MC_UPDATER_REPO=$repo
Environment=MC_UPDATER_SSH_KEY=$key
Environment=MC_UPDATER_STATE=$state
ExecStart=/usr/bin/python3 $repo/scripts/panel_updater.py
UMask=0007
NoNewPrivileges=true
TimeoutStartSec=30min
EOF
cat >"/etc/systemd/system/$unit.timer" <<EOF
[Unit]
Description=StudioCraft - verificar pedidos de atualização

[Timer]
OnBootSec=10s
OnUnitInactiveSec=5s
AccuracySec=1s
Unit=$unit.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now "$unit.timer" >/dev/null
systemctl start "$unit.service"
as_operator docker compose --project-directory "$repo" --env-file "$repo/.env" \
  -f "$repo/compose.yaml" -f "$repo/compose.panel.yaml" \
  up -d --build --no-deps painel restaurador
echo 'Atualizador instalado. Reabra o painel e use Baixar e aplicar atualizações.'
echo 'Progresso detalhado no host: journalctl -u studiocraft-panel-updater.service'
