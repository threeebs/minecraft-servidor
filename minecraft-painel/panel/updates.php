<?php
declare(strict_types=1);

function jobsDir(): string { return getenv('PANEL_JOBS_DIRECTORY') ?: '/jobs'; }
function readUpdateJson(string $name): array {
  $raw=@file_get_contents(jobsDir().'/'.$name);
  if ($raw===false || strlen($raw)>65536) return [];
  $data=json_decode($raw,true);
  return is_array($data) ? $data : [];
}
function updatePending(): bool {
  return file_exists(jobsDir().'/update.job') || file_exists(jobsDir().'/update.working');
}
function maintenanceLock() {
  $lock=@fopen(jobsDir().'/backup.lock','c');
  if (!$lock || !flock($lock,LOCK_EX|LOCK_NB)) {
    if ($lock) fclose($lock);
    throw new RuntimeException('Uma operação do servidor está em andamento. Aguarde.');
  }
  return $lock;
}
function releaseMaintenanceLock($lock): void { flock($lock,LOCK_UN); fclose($lock); }
function updateStatus(): array {
  $worker=readUpdateJson('update-worker.json');
  $ready=($worker['ready']??false)===true && time()-(int)($worker['heartbeat']??0)<30;
  $data=readUpdateJson('update-status.json');
  $queued=readUpdateJson('update.job');
  if ($queued) $data=['id'=>$queued['id']??'', 'state'=>'queued','message'=>'Atualização na fila.','events'=>[]];
  $busy=updatePending();
  return array_merge(['state'=>'idle','message'=>$ready?'Pronto para atualizar.':'Atualizador não configurado ou indisponível.',
    'events'=>[],'current'=>$worker['current']??''], $data,
    ['ready'=>$ready,'busy'=>$busy,'can_update'=>$ready && !$busy]);
}
function requestUpdate(): array {
  $lock=maintenanceLock();
  try {
    $status=updateStatus();
    if ($status['busy']) throw new RuntimeException('Já existe uma atualização pendente.');
    if (!$status['ready']) throw new RuntimeException('Atualizador indisponível. Verifique a configuração no Ubuntu.');
    if (glob(jobsDir().'/restore-*.job') || glob(jobsDir().'/restore-*.working') || file_exists(jobsDir().'/backup-in-progress')) {
      throw new RuntimeException('Backup ou restauração em andamento. Aguarde antes de atualizar.');
    }
    // A fila contém apenas um identificador: o navegador não escolhe comandos, repositório ou branch.
    $id=bin2hex(random_bytes(16));
    $temp=jobsDir().'/update-'.$id.'.tmp';
    $body=json_encode(['id'=>$id,'requested_at'=>gmdate('c')],JSON_THROW_ON_ERROR);
    if (file_put_contents($temp,$body,LOCK_EX)===false) throw new RuntimeException('Não foi possível registrar a atualização.');
    chmod($temp,0660);
    if (!rename($temp,jobsDir().'/update.job')) {
      @unlink($temp);
      throw new RuntimeException('Não foi possível enfileirar a atualização.');
    }
    return updateStatus();
  } finally { releaseMaintenanceLock($lock); }
}
