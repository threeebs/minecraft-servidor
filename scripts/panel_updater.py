#!/usr/bin/env python3
"""Consumidor da fila do painel, executado no Ubuntu pelo systemd (não no PHP)."""
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
import traceback
from datetime import datetime, timezone

REPOSITORY = 'git@github.com:threeebs/minecraft-servidor.git'


class UpdateError(Exception):
    pass


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(data, stream, ensure_ascii=False)
    temp.chmod(0o660)
    temp.replace(path)


def services_changed(paths):
    selected = set()
    for path in paths:
        if path in ('compose.yaml', 'compose.panel.yaml'):
            selected.update(('minecraft', 'painel', 'restaurador'))
        elif path == 'Dockerfile.minecraft':
            selected.add('minecraft')
        elif path.startswith('minecraft-painel/panel/'):
            selected.add('painel')
        elif path.startswith('minecraft-painel/worker/'):
            selected.add('restaurador')
        else:
            # O contexto de build do Minecraft é a raiz do projeto. Qualquer outro
            # arquivo novo pode ser usado pelo Dockerfile em versões futuras.
            if not (path.endswith('.md') or path.startswith(('tests/', 'scripts/')) or
                    path in ('.gitignore', '.env.example', 'config.yml')):
                selected.add('minecraft')
    return sorted(selected)


def protected_path(path):
    return (path == '.env' or path.startswith('.env.') and path != '.env.example' or
            path.split('/')[0] in ('data', 'world', 'world_nether', 'world_the_end', '.git') or
            path.startswith(('minecraft-painel/jobs/', 'minecraft-painel/backups/')))


class Updater:
    def __init__(self, repo, key, state):
        self.repo = Path(repo).resolve()
        self.key = Path(key).resolve()
        self.state_dir = Path(state).resolve()
        self.jobs = self.repo / 'minecraft-painel/jobs'
        self.status = {'state': 'running', 'message': '', 'events': []}
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
        self.env['GIT_SSH_COMMAND'] = ' '.join(shlex.quote(word) for word in (
            'ssh', '-i', str(self.key), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10'))
        self.project = ''
        self.log = None

    def command(self, args, error, cwd=None, timeout=120, capture=True):
        try:
            result = subprocess.run(args, cwd=cwd or self.repo, env=self.env,
                                    stdout=subprocess.PIPE if capture else self.log,
                                    stderr=self.log, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(error) from exc
        if result.returncode:
            raise UpdateError(error)
        return (result.stdout or '').strip()

    def git(self, *args, error='Não foi possível consultar o repositório.'):
        return self.command(['git', *args], error)

    def compose(self, root, *args, timeout=900, capture=True):
        return self.command(['docker', 'compose', '--project-name', self.project,
            '--project-directory', str(root), '--env-file', str(self.repo / '.env'),
            '-f', str(root / 'compose.yaml'), '-f', str(root / 'compose.panel.yaml'), *args],
            'A etapa Docker falhou. Consulte o registro privado no Ubuntu.',
            timeout=timeout, capture=capture)

    def event(self, message, state='running'):
        self.status['state'] = state
        self.status['message'] = message
        self.status['updated_at'] = timestamp()
        self.status['events'].append({'time': timestamp(), 'message': message})
        self.status['events'] = self.status['events'][-30:]
        atomic_json(self.jobs / 'update-status.json', self.status)

    def worker(self, ready=True):
        current = self.git('rev-parse', 'HEAD')
        atomic_json(self.jobs / 'update-worker.json', {
            'ready': ready, 'heartbeat': int(time.time()), 'current': current})

    def clean_main(self, expected=None):
        if self.git('branch', '--show-current') != 'main':
            raise UpdateError('Coloque o repositório na branch main antes de atualizar.')
        if self.git('status', '--porcelain'):
            raise UpdateError('Existem alterações locais. Salve-as no Git antes de atualizar.')
        if expected and self.git('rev-parse', 'HEAD') != expected:
            raise UpdateError('A revisão local mudou durante a atualização. Pedido cancelado.')

    def project_info(self):
        raw = self.command(['docker', 'inspect', 'minecraft-server'], 'Minecraft não encontrado no Docker.')
        info = json.loads(raw)[0]
        labels = info['Config'].get('Labels') or {}
        project = labels.get('com.docker.compose.project', '')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
            raise UpdateError('Não foi possível identificar o projeto Docker do Minecraft.')
        working = labels.get('com.docker.compose.project.working_dir', '')
        if not working or Path(working).resolve() != self.repo:
            raise UpdateError('O Minecraft ativo pertence a outra pasta. Atualização cancelada.')
        self.project = project

    def archive(self, target, stage):
        archive = stage / 'source.tar'
        self.git('archive', '--format=tar', '-o', str(archive), target)
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or protected_path(member.name) or
                        not (member.isfile() or member.isdir())):
                    raise UpdateError('A revisão contém dados locais ou links não permitidos.')
            # Os membros foram validados e a pasta temporária não contém links.
            source.extractall(stage, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
        archive.unlink()
        for path in ('compose.yaml', 'compose.panel.yaml', 'scripts/panel_updater.py'):
            if not (stage / path).is_file():
                raise UpdateError('A revisão não contém os arquivos obrigatórios do projeto.')

    def images(self, spec, selected):
        images = {}
        for service in selected:
            ids = self.compose(self.repo, 'ps', '--all', '--quiet', service).splitlines()
            if not ids:
                raise UpdateError('Serviço não instalado: ' + service + '. Execute a instalação no Ubuntu.')
            image = self.command(['docker', 'inspect', '--format', '{{.Image}}', ids[0]],
                                 'Não foi possível preservar a imagem anterior.')
            tag = spec['services'][service].get('image') or self.project + '-' + service
            images[tag] = image
        return images

    def wait_services(self, selected):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                for service in selected:
                    ids = self.compose(self.repo, 'ps', '--all', '--quiet', service).splitlines()
                    if not ids:
                        raise UpdateError('Serviço não encontrado.')
                    raw = self.command(['docker', 'inspect', ids[0]], 'Serviço indisponível.')
                    state = json.loads(raw)[0]['State']
                    if not state['Running'] or state.get('Health', {}).get('Status', 'healthy') != 'healthy':
                        raise UpdateError('Serviço ainda está iniciando.')
                    if service == 'painel':
                        self.command(['docker', 'exec', ids[0], 'php', '-r',
                            'exit(@file_get_contents("http://127.0.0.1/")===false ? 1 : 0);'],
                            'Painel ainda está iniciando.', timeout=10)
                    elif service == 'minecraft':
                        self.command(['docker', 'exec', ids[0], 'rcon-cli', 'list'],
                                     'Minecraft/RCON ainda está iniciando.', timeout=10)
                return
            except UpdateError:
                time.sleep(3)
        raise UpdateError('Os serviços não responderam após a atualização.')

    def apply(self):
        self.clean_main()
        old = self.git('rev-parse', 'HEAD')
        self.status['current'] = old
        self.event('Verificando o servidor e baixando a main…')
        self.project_info()
        self.git('fetch', '--no-tags', REPOSITORY, 'main',
                 error='Não foi possível baixar a main. Confira a chave de leitura e a conexão no Ubuntu.')
        target = self.git('rev-parse', 'FETCH_HEAD')
        if not re.fullmatch(r'[a-f0-9]{40}', target):
            raise UpdateError('Revisão remota inválida.')
        self.status['target'] = target
        if target == old:
            self.wait_services(['minecraft', 'painel', 'restaurador'])
            self.event('O servidor já está na versão mais recente da main.', 'success')
            return
        self.git('merge-base', '--is-ancestor', old, target,
                 error='A main local divergiu do GitHub. Resolva a divergência antes de atualizar.')
        paths = self.git('diff', '--name-only', old, target).splitlines()
        selected = services_changed(paths)
        old_spec = json.loads(self.compose(self.repo, 'config', '--format', 'json'))
        previous_images = self.images(old_spec, selected)
        changed = False
        deployed = False
        with tempfile.TemporaryDirectory(prefix='build-', dir=self.state_dir) as folder:
            stage = Path(folder)
            self.archive(target, stage)
            self.compose(stage, 'config', '--quiet')
            new_spec = json.loads(self.compose(stage, 'config', '--format', 'json'))
            build = [service for service in selected if 'build' in new_spec['services'][service]]
            candidate_tags = {service: 'studiocraft-update-' + self.status['id'] + '-' + service for service in build}
            override = stage / 'update-build.json'
            override.write_text(json.dumps({'services': {name: {'image': tag} for name, tag in candidate_tags.items()}}))
            try:
                if build:
                    self.event('Preparando as novas imagens. Os serviços atuais continuam online…')
                    # Tags isoladas: uma falha/timeout no build não altera imagens de produção.
                    self.compose(stage, '-f', str(override), 'build', *build, capture=False)
                self.clean_main(expected=old)
                self.git('merge', '--ff-only', target, error='Não foi possível avançar a main local.')
                changed = True
                for service, candidate in candidate_tags.items():
                    tag = new_spec['services'][service].get('image') or self.project + '-' + service
                    self.command(['docker', 'tag', candidate, tag], 'Não foi possível aplicar a nova imagem.')
                if selected:
                    self.event('Aplicando a atualização e reiniciando os serviços alterados…')
                    if 'minecraft' in selected:
                        self.command(['docker', 'exec', 'minecraft-server', 'rcon-cli', 'save-all flush'],
                                     'Não foi possível salvar o mundo antes da atualização.')
                    deployed = True
                    self.compose(self.repo, 'up', '-d', '--no-build', '--no-deps', '--force-recreate',
                                 '--timeout', '60', *selected, timeout=300, capture=False)
                    self.event('Confirmando que os serviços estão respondendo…')
                    self.wait_services(selected)
                self.status['current'] = target
                self.event('Atualização concluída. Versão ' + target[:12] + ' instalada.', 'success')
            except Exception:
                if changed:
                    self.event('A aplicação falhou. Recuperando o código e as imagens anteriores…')
                    try:
                        for tag, image in previous_images.items():
                            self.command(['docker', 'tag', image, tag], 'Falha ao recuperar a imagem anterior.')
                        # --keep não descarta edições feitas pelo operador durante a atualização.
                        self.git('reset', '--keep', old, error='Alterações locais impedem recuperar a revisão anterior.')
                        if deployed:
                            self.compose(self.repo, 'up', '-d', '--no-build', '--no-deps', '--force-recreate',
                                         '--timeout', '60', *selected, timeout=300, capture=False)
                            self.wait_services(selected)
                        self.status['current'] = old
                        self.event('Código e imagens anteriores recuperados. A atualização não foi aplicada.', 'error')
                    except Exception as recovery_error:
                        raise UpdateError('Falha na recuperação. Verifique os serviços e o registro privado no Ubuntu.') from recovery_error
                raise
            finally:
                for tag in candidate_tags.values():
                    try:
                        self.command(['docker', 'image', 'rm', tag], 'Limpeza adiada.', capture=False)
                    except UpdateError:
                        pass

    def run_once(self):
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_dir.chmod(0o700)
        self.jobs.mkdir(parents=True, exist_ok=True)
        if not self.key.is_file() or self.key.stat().st_mode & 0o077:
            self.worker(False)
            return
        with (self.state_dir / 'last-command.log').open('a') as self.log:
            os.chmod(self.log.name, 0o600)
            self.worker(not (self.jobs / 'update.working').exists())
            with (self.jobs / 'backup.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                queued = self.jobs / 'update.job'
                working = self.jobs / 'update.working'
                if working.exists() or not queued.exists():
                    return
                if (list(self.jobs.glob('restore-*.job')) or list(self.jobs.glob('restore-*.working')) or
                        (self.jobs / 'backup-in-progress').exists()):
                    return
                queued.replace(working)
                try:
                    if working.stat().st_size > 4096:
                        raise UpdateError('Pedido de atualização inválido.')
                    request = json.loads(working.read_text())
                    if set(request) != {'id', 'requested_at'} or not re.fullmatch(r'[a-f0-9]{32}', request['id']):
                        raise UpdateError('Pedido de atualização inválido.')
                    self.status['id'] = request['id']
                    self.status['requested_at'] = request['requested_at']
                    self.apply()
                except Exception as exc:
                    traceback.print_exc(file=self.log)
                    message = str(exc) if isinstance(exc, UpdateError) else 'Falha interna. Consulte o registro privado no Ubuntu.'
                    self.event(message, 'error')
                finally:
                    working.unlink(missing_ok=True)
                    self.worker()


if __name__ == '__main__':
    os.umask(0o007)
    Updater(os.environ['MC_UPDATER_REPO'], os.environ['MC_UPDATER_SSH_KEY'],
            os.environ['MC_UPDATER_STATE']).run_once()
