"""Git real em repositórios temporários e Docker simulado; não acessa produção."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import fcntl

MODULE = Path(__file__).resolve().parents[1] / 'scripts/panel_updater.py'
spec = importlib.util.spec_from_file_location('panel_updater', MODULE)
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class FakeDocker(updater.Updater):
    def __init__(self, *args):
        super().__init__(*args)
        self.calls = []
        self.tags = {}
        self.fail_build = False
        self.fail_up = False
        self.fail_save = False
        self.during_build = None

    def command(self, args, error, **kwargs):
        self.calls.append(list(args))
        if args[0] == 'git':
            return super().command(args, error, **kwargs)
        if args[1] == 'inspect':
            if '--format' in args:
                return 'sha256:previous-' + args[-1].removeprefix('cid-')
            return json.dumps([{'Image': 'sha256:previous', 'Config': {'Labels': {
                'com.docker.compose.project': 'studio-custom',
                'com.docker.compose.project.working_dir': str(self.repo)}}, 'State': {'Running': True}}])
        if args[1] == 'compose':
            root = Path(args[args.index('--project-directory') + 1])
            if 'config' in args:
                return json.dumps({'services': {
                    'minecraft': {'image': 'minecraft-production:26.2', 'build': '.'},
                    'painel': {'build': 'minecraft-painel/panel'},
                    'restaurador': {'image': 'docker:27-cli'}}}) if '--format' in args else ''
            if 'ps' in args:
                return 'cid-' + args[-1]
            if 'build' in args:
                self.build_head = git(self.repo, 'rev-parse', 'HEAD')
                if self.during_build:
                    self.during_build()
                if self.fail_build:
                    raise updater.UpdateError('Build simulado falhou.')
                self.assert_isolated = 'studiocraft-update-' in (root / 'update-build.json').read_text()
            if 'up' in args and self.fail_up:
                self.fail_up = False
                raise updater.UpdateError('Aplicação simulada falhou.')
            return ''
        if args[1] == 'tag':
            self.tags[args[3]] = args[2]
        if self.fail_save and 'save-all flush' in args:
            raise updater.UpdateError('RCON indisponível para salvar o mundo.')
        return ''


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.author = root / 'author'
        self.author.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.author)], check=True)
        git(self.author, 'config', 'user.name', 'Test')
        git(self.author, 'config', 'user.email', 'test@example.invalid')
        files = {'.gitignore': '.env\ndata/\nminecraft-painel/jobs/\n',
                 'compose.yaml': '{}\n', 'compose.panel.yaml': '{}\n',
                 'scripts/panel_updater.py': '# updater\n',
                 'minecraft-painel/panel/index.php': '<?php echo "old";\n'}
        for path, text in files.items():
            p = self.author / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.author, 'add', '.')
        git(self.author, 'commit', '-qm', 'initial')
        self.old = git(self.author, 'rev-parse', 'HEAD')
        self.remote = root / 'remote.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(self.author), str(self.remote)], check=True)
        self.repo = root / 'server'
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.repo)], check=True)
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / '.env').write_text('PRIVATE_PASSWORD=never-print\n')
        (self.repo / 'data').mkdir()
        (self.repo / 'data/world.bin').write_bytes(b'world-sentinel')
        self.jobs = self.repo / 'minecraft-painel/jobs'
        self.jobs.mkdir()
        self.key = root / 'key'
        self.key.write_text('fake-private-key')
        self.key.chmod(0o600)
        self.worker = FakeDocker(self.repo, self.key, root / 'state')
        self.pin = patch.object(updater, 'REPOSITORY', str(self.remote))
        self.pin.start()

    def tearDown(self):
        self.pin.stop()
        self.assertEqual((self.repo / '.env').read_text(), 'PRIVATE_PASSWORD=never-print\n')
        self.assertEqual((self.repo / 'data/world.bin').read_bytes(), b'world-sentinel')
        self.temp.cleanup()

    def publish(self, path='minecraft-painel/panel/index.php', text='<?php echo "new";\n'):
        p = self.author / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        git(self.author, 'add', '-f', path)
        git(self.author, 'commit', '-qm', 'update')
        git(self.author, 'push', str(self.remote), 'main')
        return git(self.author, 'rev-parse', 'HEAD')

    def request(self, **extra):
        request = {'id': 'a' * 32, 'requested_at': '2026-10-14T04:00:00Z', **extra}
        (self.jobs / 'update.job').write_text(json.dumps(request))

    def run_job(self):
        self.request()
        self.worker.run_once()
        self.assertFalse((self.jobs / 'update.working').exists())
        return json.loads((self.jobs / 'update-status.json').read_text())

    def test_success_prebuild_and_only_panel_restarted(self):
        target = self.publish()
        result = self.run_job()
        self.assertEqual(result['state'], 'success')
        self.assertEqual(result['current'], target)
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), target)
        self.assertEqual(self.worker.build_head, self.old)
        self.assertTrue(self.worker.assert_isolated)
        ups = [c for c in self.worker.calls if 'up' in c]
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0][-1], 'painel')
        self.assertNotIn('minecraft', ups[0])
        self.assertIn('studio-custom', ups[0])
        self.assertNotIn('never-print', json.dumps(result))

    def test_no_updates_does_not_build_or_restart(self):
        self.assertEqual(self.run_job()['state'], 'success')
        self.assertFalse(any('build' in c or 'up' in c for c in self.worker.calls))

    def test_dirty_repository_is_preserved(self):
        self.publish()
        path = self.repo / 'minecraft-painel/panel/index.php'
        path.write_text('local-work')
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(path.read_text(), 'local-work')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.old)

    def test_wrong_branch_is_preserved(self):
        git(self.repo, 'switch', '-c', 'operator-work')
        result = self.run_job()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(git(self.repo, 'branch', '--show-current'), 'operator-work')

    def test_divergent_main_is_not_reset(self):
        self.publish()
        (self.repo / 'local.md').write_text('local')
        git(self.repo, 'add', 'local.md')
        git(self.repo, 'commit', '-qm', 'local')
        local = git(self.repo, 'rev-parse', 'HEAD')
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), local)

    def test_build_failure_keeps_code_and_containers(self):
        self.publish()
        self.worker.fail_build = True
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.old)
        self.assertFalse(any('up' in c or 'tag' in c for c in self.worker.calls))

    def test_deployment_failure_recovers_code_and_images(self):
        self.publish()
        self.worker.fail_up = True
        result = self.run_job()
        self.assertEqual(result['state'], 'error')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.old)
        self.assertEqual(self.worker.tags['studio-custom-painel'], 'sha256:previous-painel')
        self.assertEqual(len([c for c in self.worker.calls if 'up' in c]), 2)
        self.assertTrue(any('recuperados' in e['message'] for e in result['events']))

    def test_concurrent_edit_during_build_is_preserved(self):
        self.publish()
        path = self.repo / 'minecraft-painel/panel/index.php'
        self.worker.during_build = lambda: path.write_text('operator-edit')
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(path.read_text(), 'operator-edit')
        self.assertFalse(any('up' in c for c in self.worker.calls))

    def test_backup_lock_defers_without_consuming_request(self):
        self.request()
        with (self.jobs / 'backup.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.worker.run_once()
        self.assertTrue((self.jobs / 'update.job').exists())
        self.assertFalse((self.jobs / 'update.working').exists())

    def test_restore_and_backup_marker_defer(self):
        for marker in ('restore-abc.job', 'restore-abc.working', 'backup-in-progress'):
            with self.subTest(marker=marker):
                self.request()
                (self.jobs / marker).touch()
                self.worker.run_once()
                self.assertTrue((self.jobs / 'update.job').exists())
                (self.jobs / marker).unlink()

    def test_interrupted_job_blocks_new_update(self):
        (self.jobs / 'update.working').write_text('{}')
        self.worker.run_once()
        self.assertFalse(json.loads((self.jobs / 'update-worker.json').read_text())['ready'])
        self.assertTrue((self.jobs / 'update.working').exists())

    def test_arbitrary_arguments_in_queue_are_rejected(self):
        self.request(command='rm -rf /', repository='attacker', branch='other')
        self.worker.run_once()
        self.assertEqual(json.loads((self.jobs / 'update-status.json').read_text())['state'], 'error')
        self.assertFalse(any('fetch' in c for c in self.worker.calls))

    def test_remote_cannot_replace_env(self):
        self.publish('.env', 'attacker=1\n')
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.old)

    def test_minecraft_changes_save_world_before_recreate(self):
        self.publish('Dockerfile.minecraft', 'FROM example\n')
        self.assertEqual(self.run_job()['state'], 'success')
        save = next(i for i, c in enumerate(self.worker.calls) if 'save-all flush' in c)
        deploy = next(i for i, c in enumerate(self.worker.calls) if 'up' in c)
        self.assertLess(save, deploy)

    def test_bad_private_key_permissions_disable_worker(self):
        self.key.chmod(0o644)
        self.request()
        self.worker.run_once()
        self.assertFalse(json.loads((self.jobs / 'update-worker.json').read_text())['ready'])
        self.assertTrue((self.jobs / 'update.job').exists())

    def test_save_failure_does_not_recreate_minecraft(self):
        self.publish('Dockerfile.minecraft', 'FROM example\n')
        self.worker.fail_save = True
        self.assertEqual(self.run_job()['state'], 'error')
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), self.old)
        self.assertFalse(any('up' in c for c in self.worker.calls))


if __name__ == '__main__':
    unittest.main()
