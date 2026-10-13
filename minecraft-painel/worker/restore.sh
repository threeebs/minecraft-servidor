#!/bin/sh
# Controlador isolado: apenas este container recebe o socket Docker.
# Aceita somente nomes de snapshots criados pelo painel (nenhum comando arbitrário).
set -u
mkdir -p /jobs
say() { printf '%s | %s\n' "$(date -u +'%Y-%m-%d %H:%M:%S UTC')" "$1" > /jobs/latest.status; }
validate_snapshot() {
  case "$1" in world-????????-??????-??????.tar.gz) ;; *) return 1;; esac
  [ -f "/backups/$1" ] && [ -f "/backups/$1.sha256" ] && [ -f "/backups/$1.roots" ] || return 1
  # O checksum garante que o archive não foi alterado depois de criado.
  expected=$(cat "/backups/$1.sha256")
  actual=$(sha256sum "/backups/$1" | cut -d' ' -f1)
  [ "$actual" = "$expected" ] || return 1
  [ -s "/backups/$1.roots" ] || return 1
  while IFS= read -r root || [ -n "$root" ]; do
    echo "$root" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$' || return 1
  done < "/backups/$1.roots"
  # Não restaurar nomes absolutos, .. ou entradas que não pertençam aos mundos declarados.
  tar -tzf "/backups/$1" | while IFS= read -r entry; do
    case "$entry" in /*|../*|*/../*|*/..|*'/./'*|*'\\'*) exit 1;; esac
    entryroot=${entry%%/*}
    grep -Fxq "$entryroot" "/backups/$1.roots" || exit 1
  done
}
restore_one() {
  job=$1
  snapshot=$(head -n 1 "$job" | tr -d '\r\n')
  id=${job##*/}; id=${id%.working}
  if ! validate_snapshot "$snapshot"; then say "FALHA: snapshot inválido ou checksum diferente: $snapshot"; return 1; fi
  say "Preparando restauração de $snapshot; extraindo para área temporária..."
  stage="/mc-data/.restore-stage-$id"
  safety="/mc-data/.pre-restore-$id"
  if [ -e "$stage" ] || [ -e "$safety" ]; then say 'FALHA: diretório temporário já existe.'; return 1; fi
  mkdir -p "$stage" "$safety" || return 1
  if ! tar -xzf "/backups/$snapshot" -C "$stage"; then
    say 'FALHA: não foi possível extrair o snapshot. Mundo atual intacto.'
    rm -rf "$stage" "$safety"
    return 1
  fi
  # Esperar qualquer backup iniciado um pouco antes do pedido de restauração.
  while [ -f /jobs/backup-in-progress ]; do sleep 2; done
  say "Snapshot extraído. Desligando Minecraft para troca segura do mundo..."
  if ! docker stop --time 60 minecraft-server >/dev/null; then
    say 'FALHA: não foi possível parar o Minecraft. Mundo atual intacto.'
    rm -rf "$stage" "$safety"
    return 1
  fi
  # Move os mundos existentes para uma cópia de emergência ANTES da substituição.
  # Os nomes das dimensões vêm do manifesto gerado junto com o snapshot.
  while IFS= read -r root || [ -n "$root" ]; do
    if [ -e "/mc-data/$root" ]; then mv "/mc-data/$root" "$safety/$root" || {
      say "ERRO ao mover $root. Minecraft permanece parado; veja /data/.pre-restore-*"; return 1;
    }; fi
  done < "/backups/$snapshot.roots"
  if ! (cd "$stage" && for root in *; do mv "$root" "/mc-data/$root" || exit 1; done); then
    say "ERRO ao aplicar o snapshot. Minecraft permanece parado! Recupere a pasta $safety manualmente."
    return 1
  fi
  rmdir "$stage" 2>/dev/null || true
  say "Mundo restaurado de $snapshot. Iniciando Minecraft..."
  if docker start minecraft-server >/dev/null; then
    say "CONCLUÍDO: $snapshot aplicado. Minecraft reiniciado. Cópia anterior em $safety"
    return 0
  fi
  say "ATENÇÃO: mundo restaurado, mas o Minecraft não iniciou. Execute docker compose logs minecraft. Cópia anterior: $safety"
  return 1
}
say 'Restaurador inicializado. Aguardando pedidos.'
while :; do
  for f in /jobs/restore-*.job; do
    [ -f "$f" ] || continue
    working=${f%.job}.working
    mv "$f" "$working" 2>/dev/null || continue
    restore_one "$working" || true
    mv "$working" "${working%.working}.done" 2>/dev/null || true
  done
  sleep 3
done
