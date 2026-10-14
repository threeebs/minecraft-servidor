<?php
declare(strict_types=1);
ini_set('display_errors', '0');
ini_set('log_errors', '1');
ini_set('max_execution_time', '0');
session_set_cookie_params(['httponly'=>true, 'secure'=>!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off', 'samesite'=>'Strict']);
session_start();
header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
header('Referrer-Policy: no-referrer');
header('Cache-Control: no-store');
function e(string $s): string { return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'); }
function logged(): bool { return !empty($_SESSION['auth']); }
function csrf(): string { return $_SESSION['csrf'] ??= bin2hex(random_bytes(32)); }
function jsonResponse(array $data, int $status=200): never {
  http_response_code($status);
  header('Content-Type: application/json; charset=utf-8');
  echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
  exit;
}
function assertCsrf(): void {
  if (!is_string($_POST['csrf'] ?? null) || !hash_equals(csrf(), $_POST['csrf'])) {
    if (($_POST['format'] ?? '')==='json') jsonResponse(['error'=>'CSRF inválido. Atualize a página.'],403);
    http_response_code(403); exit('CSRF inválido.');
  }
}
function consoleEntry(string $command, string $response, bool $error=false): void {
  // Histórico limitado à sessão autenticada, sem gravar comandos no navegador.
  $history=$_SESSION['console'] ?? [];
  $history[]=['command'=>$command,'response'=>strlen($response)>32768 ? substr($response,0,32768)."\n[Histórico abreviado]" : $response,'error'=>$error];
  $_SESSION['console']=array_slice($history,-50);
}
function alert(string $msg, string $type='info'): void { $_SESSION['flash']=['msg'=>$msg,'type'=>$type]; }
function redirect(): never { header('Location: /', true, 303); exit; }
function dirInit(): void { foreach (['/backups','/jobs'] as $dir) if (!is_dir($dir) || !is_writable($dir)) throw new RuntimeException("Diretório sem acesso de escrita: $dir"); }
require __DIR__ . '/rcon.php';
function worlds(): array {
  $properties=@file_get_contents('/mc-data/server.properties') ?: '';
  preg_match('/^level-name\s*=\s*(.+)$/m', $properties, $m);
  $base=trim($m[1] ?? 'world');
  if (!preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/D',$base)) throw new RuntimeException('Nome do mundo inesperado.');
  $roots=[];
  foreach ([$base, $base.'_nether', $base.'_the_end'] as $name) {
    if (is_dir('/mc-data/'.$name) && !is_link('/mc-data/'.$name)) $roots[]=$name;
  }
  if (!is_file('/mc-data/'.$base.'/level.dat')) throw new RuntimeException('Mundo não encontrado em /data/'.$base.'.');
  return $roots;
}
function backup(): string {
  dirInit();
  $lock=fopen('/jobs/backup.lock','c');
  if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) throw new RuntimeException('Já existe um backup em andamento.');
  if (glob('/jobs/restore-*.job') || glob('/jobs/restore-*.working')) throw new RuntimeException('Restauração pendente; não faça backup agora.');
  $rcon=new Rcon();
  $name='world-'.gmdate('Ymd-His').'-'.bin2hex(random_bytes(3));
  $out='/backups/'.$name.'.tar.gz'; $tmp=$out.'.part';
  $paused=false;
  if (file_put_contents('/jobs/backup-in-progress', (string)getmypid())===false) throw new RuntimeException('Não foi possível criar sinalizador de backup.');
  try {
    $roots=worlds();
    $rcon->command('save-off'); $paused=true;
    $rcon->command('save-all flush');
    $command=array_merge(['tar','-czf',$tmp,'-C','/mc-data','--'], $roots);
    $proc=proc_open($command,[1=>['pipe','w'],2=>['pipe','w']],$pipes);
    if (!is_resource($proc)) throw new RuntimeException('Não foi possível iniciar o tar.');
    $error=stream_get_contents($pipes[2]); fclose($pipes[2]); fclose($pipes[1]);
    $code=proc_close($proc);
    if ($code!==0) throw new RuntimeException('Erro no tar: '.substr($error,0,300));
    if (!rename($tmp,$out)) throw new RuntimeException('Não foi possível finalizar o arquivo de backup.');
    if (file_put_contents($out.'.sha256',hash_file('sha256',$out))===false || file_put_contents($out.'.roots',implode("\n",$roots)."\n")===false) throw new RuntimeException('Erro ao gerar os metadados.');
    return basename($out);
  } finally {
    if ($paused) { try { $rcon->command('save-on'); } catch (Throwable $ex) { error_log('ALERTA: Falha ao executar save-on: '.$ex->getMessage()); } }
    if (is_file($tmp)) @unlink($tmp);
    @unlink('/jobs/backup-in-progress');
    flock($lock,LOCK_UN); fclose($lock);
  }
}
function listBackups(): array {
  $all=glob('/backups/world-*.tar.gz') ?: [];
  $all=array_values(array_filter($all,fn($path)=>is_file($path.'.sha256') && is_file($path.'.roots')));
  usort($all,fn($a,$b)=>filemtime($b)<=>filemtime($a));
  return array_slice($all,0,60);
}
if ($_SERVER['REQUEST_METHOD']==='POST') {
  $action=(string)($_POST['action']??'');
  $json=($action==='command' && ($_POST['format']??'')==='json');
  if ($json && !logged()) jsonResponse(['error'=>'Faça login novamente.'],401);
  assertCsrf();
  if ($action==='login') {
    $password=(string)getenv('PANEL_PASSWORD');
    // Uma senha forte e definida pelo operador é obrigatória.
    if (strlen($password)<16) { alert('Configure PANEL_PASSWORD com pelo menos 16 caracteres no .env.','error'); redirect(); }
    if (hash_equals($password,(string)($_POST['password']??''))) {
      session_regenerate_id(true); $_SESSION['auth']=true; $_SESSION['csrf']=bin2hex(random_bytes(32)); redirect();
    }
    usleep(400000); alert('Senha incorreta.','error'); redirect();
  }
  if (!logged()) { http_response_code(401); exit('Faça login.'); }
  if ($action==='logout') { $_SESSION=[]; session_destroy(); redirect(); }
  try {
    if ($action==='command') {
      $raw=$_POST['command']??'';
      if (!is_string($raw) || strlen($raw)>256 || preg_match('/[\r\n\x00-\x1F\x7F]/',$raw)) throw new InvalidArgumentException('Use um comando de até 256 bytes, em uma única linha.');
      $cmd=ltrim(trim($raw),'/');
      if ($cmd==='') throw new InvalidArgumentException('Digite um comando.');
      $response=(new Rcon())->command($cmd);
      $response=$response!=='' ? $response : '(Sem mensagem de retorno)';
      consoleEntry($cmd,$response);
      if ($json) {
        $result=['command'=>$cmd,'response'=>$response];
        if ($cmd==='list') $result['player_status']=$response;
        jsonResponse($result);
      }
    } elseif ($action==='backup') {
      $file=backup(); alert('Snapshot criado: '.$file,'ok');
    } elseif ($action==='restore') {
      dirInit();
      $file=(string)($_POST['file']??'');
      if (!preg_match('/^world-\d{8}-\d{6}-[a-f0-9]{6}\.tar\.gz$/D',$file) || !is_file('/backups/'.$file) || !is_file('/backups/'.$file.'.sha256') || !is_file('/backups/'.$file.'.roots')) throw new RuntimeException('Backup inválido.');
      if (($_POST['confirm']??'')!=='RESTAURAR') throw new RuntimeException('Confirmação inválida.');
      if (glob('/jobs/restore-*.job') || glob('/jobs/restore-*.working')) throw new RuntimeException('Já existe uma restauração na fila.');
      $job='restore-'.bin2hex(random_bytes(8));
      $temp='/jobs/'.$job.'.tmp';
      if (file_put_contents($temp,$file."\n",LOCK_EX)===false || !rename($temp,'/jobs/'.$job.'.job')) throw new RuntimeException('Não foi possível enfileirar a restauração.');
      alert('Restauração solicitada. O Minecraft será parado e reiniciado automaticamente. Atualize a página para acompanhar.','ok');
    } else throw new RuntimeException('Ação desconhecida.');
  } catch (Throwable $ex) {
    if ($action==='command' && isset($cmd) && $cmd!=='') consoleEntry($cmd,$ex->getMessage(),true);
    if ($json) jsonResponse(['error'=>$ex->getMessage()], $ex instanceof InvalidArgumentException ? 422 : 502);
    alert($ex->getMessage(),'error');
  }
  redirect();
}
if (isset($_GET['download'])) {
  if (!logged()) { http_response_code(401); exit('Faça login.'); }
  $file=(string)$_GET['download'];
  if (!preg_match('/^world-\d{8}-\d{6}-[a-f0-9]{6}\.tar\.gz$/D',$file) || !is_file('/backups/'.$file)) { http_response_code(404); exit; }
  header('Content-Type: application/gzip'); header('Content-Disposition: attachment; filename="'.$file.'"');
  header('Content-Length: '.filesize('/backups/'.$file)); readfile('/backups/'.$file); exit;
}
$flash=$_SESSION['flash']??null; unset($_SESSION['flash']);
$pending=(glob('/jobs/restore-*.job')?:[]) || (glob('/jobs/restore-*.working')?:[]);
$status=is_file('/jobs/latest.status')?trim((string)file_get_contents('/jobs/latest.status')):'Nenhuma restauração executada.';
try { $playerStatus=logged()?(new Rcon())->command('list'):''; } catch(Throwable $e) { $playerStatus='Minecraft/RCON indisponível: '.$e->getMessage(); }
$backups=logged()?listBackups():[];
?><!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mahal • Minecraft Admin</title><?php if ($pending): ?><meta http-equiv="refresh" content="6"><?php endif; ?>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#e8ecf5;background:#0d111b}*{box-sizing:border-box}body{margin:0}main{max-width:1060px;margin:36px auto;padding:0 20px}.top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}h1{font-size:29px;margin:4px 0}h2{font-size:19px;margin:0 0 14px}.muted{color:#9caabd;font-size:14px}p{line-height:1.55}.badge{display:inline-block;background:#123826;color:#80e6af;border:1px solid #2e8658;padding:5px 9px;border-radius:999px;font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}.wide{grid-column:1/-1}.card{background:#171e2e;border:1px solid #2c374e;border-radius:16px;padding:22px}.flash{padding:14px 18px;border-radius:10px;background:#173b30;color:#b4f8cf;white-space:pre-wrap;margin:20px 0}.flash.error{background:#482226;color:#ffbec1}button,.btn{font:inherit;background:#3cb87b;color:#071b13;border:0;padding:11px 16px;border-radius:9px;font-weight:700;cursor:pointer}button.secondary,.btn.secondary{background:#29354a;color:#e8ecf5}button.danger{background:#d85654;color:white}input{font:inherit;background:#0c1321;color:white;border:1px solid #4b5e77;border-radius:8px;padding:11px;width:100%}form.inline{display:flex;gap:9px;align-items:center}form.inline input{flex:1}.item{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:13px 0;border-top:1px solid #334157;flex-wrap:wrap}.item:first-child{border-top:0}.actions{display:flex;gap:9px;flex-wrap:wrap}small{color:#aab4c3}.dangerzone{border-color:#6f424a}code{background:#0b1322;padding:3px 5px;border-radius:5px}@media(max-width:760px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}h1{font-size:24px}form.inline{flex-wrap:wrap}}a{color:#8fe4b3}

.card{min-width:0}.console-card{padding:22px}.console-card h2{margin-bottom:0}.console-card .muted{margin:6px 0 16px}.console-output{height:340px;overflow:auto;background:#080e16;border:1px solid #334157;border-radius:10px;margin:4px 0 16px;padding:16px;font:15px/1.65 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;white-space:pre-wrap}.console-output:empty:before{content:'O console está pronto. Envie um comando abaixo.';color:#9caabd}.console-entry{margin-bottom:18px}.console-prompt{color:#80e6af}.console-response{color:#d8e2f0}.console-error .console-response{color:#ffb9bf}.console-symbol{color:#80e6af;font-size:22px}#console-form input{min-width:180px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.console-footer{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#aab4c3;font-size:14px;margin-top:12px}button:disabled{opacity:.55;cursor:wait}:focus-visible{outline:3px solid #8fe4b3;outline-offset:3px}@media(max-width:540px){main{padding:0 12px;margin:20px auto}.card{padding:18px}.console-output{height:300px;font-size:14px}#console-form button{width:100%}}
</style></head><body><main><div class="top"><div><span class="badge">MINECRAFT • ADMIN</span><h1>Servidor Mahal</h1><div class="muted">Painel local • RCON • Snapshots do mundo</div></div><?php if(logged()): ?><form method="post"><input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="logout"><button class="secondary">Sair</button></form><?php endif; ?></div>
<?php if($flash): ?><div class="flash <?=($flash['type']==='error'?'error':'')?>"><?=e($flash['msg'])?></div><?php endif; ?>
<?php if (!logged()): ?><section class="card" style="max-width:430px;margin:28px auto"><h2>Entrar no painel</h2><form method="post"><input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="login"><label>Senha de administrador</label><p><input name="password" type="password" minlength="16" autocomplete="current-password" required></p><button>Entrar</button></form></section>
<?php else: ?><div class="grid"><section class="card"><h2>Estado do servidor</h2><p id="player-status"><?=e($playerStatus)?></p><small>Conexão pelo serviço Docker <code>minecraft:25575</code>. O RCON não está exposto na internet.</small></section>
<section class="card"><h2>Comandos rápidos</h2><div class="actions"><?php foreach(['list'=>'Jogadores','time set day'=>'Dia','time set night'=>'Noite','weather clear'=>'Sem chuva','difficulty peaceful'=>'Pacífico','save-all flush'=>'Salvar mundo'] as $cmd=>$label): ?><form method="post" data-quick-command><input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="command"><input type="hidden" name="command" value="<?=e($cmd)?>"><button class="secondary" data-command><?=e($label)?></button></form><?php endforeach; ?></div></section>
<section class="card wide console-card" aria-labelledby="console-title">
  <div class="top"><div><h2 id="console-title">Terminal do Minecraft</h2><p class="muted">Envie comandos e acompanhe as respostas do servidor.</p></div><button type="button" class="secondary" id="clear-console">Limpar tela</button></div>
  <div id="console-output" class="console-output" role="log" aria-label="Histórico de comandos" aria-live="polite" tabindex="0">
    <?php foreach($_SESSION['console']??[] as $entry): ?><div class="console-entry <?=($entry['error']?'console-error':'')?>" data-command-text="<?=e($entry['command'])?>"><div class="console-prompt">&gt; <?=e($entry['command'])?></div><div class="console-response"><?=e($entry['response'])?></div></div><?php endforeach; ?>
  </div>
  <form method="post" action="/" class="inline" id="console-form">
    <input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="command">
    <label for="command" class="console-symbol" aria-hidden="true">&gt;</label>
    <input id="command" name="command" maxlength="256" placeholder="Ex.: gamemode creative Marvingames" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Comando Minecraft" aria-describedby="console-help" required>
    <button>Enviar comando</button>
  </form>
  <div class="console-footer"><span id="console-state" role="status">Pronto para enviar</span><span id="console-help">Enter envia · ↑ ↓ navega pelo histórico</span></div>
  <noscript><p class="muted">Sem JavaScript, o comando é enviado e a página é recarregada.</p></noscript>
</section>
<section class="card wide"><h2>Backup do mundo agora</h2><p>O botão pausa gravações, executa <code>save-all flush</code>, compacta os mundos (inventários incluídos) e reativa gravações. O servidor continua online durante o backup.</p><form method="post"><input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="backup"><button>⬇ Criar snapshot agora</button></form><p class="muted">Reserve espaço no disco: os snapshots são mantidos até você removê-los manualmente.</p></section>
<section class="card wide dangerzone"><h2>Voltar a um snapshot</h2><p>Ao restaurar, todos os jogadores serão desconectados. O Minecraft será parado; os dados atuais serão movidos para uma pasta de segurança; o snapshot escolhido será restaurado e o Minecraft iniciado novamente. Todo progresso posterior àquele snapshot será perdido.</p><p><b>Última restauração:</b> <?=e($status)?></p><?php if($pending): ?><p class="badge">Restauração em andamento ou aguardando... Atualização automática.</p><?php endif; ?>
<?php if(!$backups): ?><p class="muted">Nenhum snapshot ainda. Faça o primeiro backup antes de jogar.</p><?php endif; ?>
<?php foreach($backups as $path): $file=basename($path); ?><div class="item"><div><strong><?=e($file)?></strong><br><small><?=date('d/m/Y H:i:s',filemtime($path))?> • <?=number_format(filesize($path)/1048576,1,',','.')?> MB</small></div><div class="actions"><a class="btn secondary" href="?download=<?=rawurlencode($file)?>">Baixar</a><form method="post" onsubmit="return confirm('ATENÇÃO: restaurar <?=e($file)?>? Progresso posterior será perdido, e o servidor será reiniciado.');"><input type="hidden" name="csrf" value="<?=e(csrf())?>"><input type="hidden" name="action" value="restore"><input type="hidden" name="file" value="<?=e($file)?>"><input type="hidden" name="confirm" value="RESTAURAR"><button class="danger" <?=($pending?'disabled':'')?>>Restaurar este backup</button></form></div></div><?php endforeach; ?></section></div><?php endif; ?></main><?php if(logged()): ?><script src="console.js?v=<?=filemtime(__DIR__.'/console.js')?>" defer></script><?php endif; ?></body></html>
