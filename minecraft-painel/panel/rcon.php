<?php
declare(strict_types=1);
final class Rcon {
  private $fp;
  private int $next = 1;
  function __construct() {
    $host = getenv('MC_RCON_HOST') ?: 'minecraft';
    $port = (int)(getenv('MC_RCON_PORT') ?: 25575);
    $this->fp=@stream_socket_client("tcp://$host:$port", $errno, $errstr, 3);
    if (!$this->fp) throw new RuntimeException('RCON indisponível: aguarde o Minecraft inicializar.');
    stream_set_timeout($this->fp, 5);
    $id=$this->next++;
    $this->send($id, 3, (string)getenv('MC_RCON_PASSWORD'));
    for ($i=0; $i<3; $i++) {
      [$rid,$type] = $this->recv();
      if ($rid === -1) throw new RuntimeException('Senha RCON incorreta. Confira o .env e recrie o container Minecraft.');
      if ($rid === $id && $type === 2) return;
    }
    throw new RuntimeException('O RCON não confirmou a autenticação.');
  }
  private function read(int $len): string {
    $out='';
    while (strlen($out)<$len) {
      $chunk=fread($this->fp, $len-strlen($out));
      if ($chunk===false || $chunk==='') {
        $meta=stream_get_meta_data($this->fp);
        throw new RuntimeException($meta['timed_out'] ? 'Tempo limite do RCON excedido. O comando pode ter sido executado; confira antes de repetir.' : 'Conexão RCON interrompida.');
      }
      $out.=$chunk;
    }
    return $out;
  }
  private function send(int $id,int $type,string $body): void {
    $packet=pack('V',strlen($body)+10).pack('V',$id).pack('V',$type).$body."\0\0";
    while ($packet!=='') {
      $n=fwrite($this->fp,$packet);
      if ($n===false || $n===0) throw new RuntimeException('Falha ao escrever no RCON.');
      $packet=substr($packet,$n);
    }
  }
  private function recv(): array {
    $size=unpack('V', $this->read(4))[1];
    if ($size<10 || $size>1048576) throw new RuntimeException('Resposta RCON inválida.');
    $raw=$this->read($size);
    $head=unpack('Vid/Vtype', substr($raw,0,8));
    $id=$head['id']===4294967295?-1:$head['id'];
    return [$id,$head['type'],substr($raw,8,-2)];
  }
  function command(string $cmd): string {
    $id=$this->next++;
    $end=$this->next++;
    $this->send($id, 2, $cmd);
    // Minecraft responde ao tipo desconhecido com o mesmo ID.
    // O marcador encerra a leitura mesmo quando a resposta vem em vários pacotes.
    $this->send($end, 0, '');
    $response='';
    for ($i=0; $i<1024; $i++) {
      [$rid,$type,$body]=$this->recv();
      if ($rid===$end) return $response;
      if ($rid!==$id || $type!==0) throw new RuntimeException('Resposta RCON inesperada.');
      $response.=$body;
      if (strlen($response)>1048576) throw new RuntimeException('Resposta RCON excede 1 MB.');
    }
    throw new RuntimeException('Resposta RCON excede o limite de pacotes.');
  }
  function __destruct() { if (is_resource($this->fp)) fclose($this->fp); }
}
