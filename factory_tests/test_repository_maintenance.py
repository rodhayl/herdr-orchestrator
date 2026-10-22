"""Offline regression tests for portable, non-invasive repository maintenance."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import factory, context

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryMaintenanceTests(unittest.TestCase):
    def test_bootstrap_uses_its_own_repo_and_does_not_invent_session_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            project = base / 'project'
            other = base / 'unrelated'
            for path in (project, other):
                path.mkdir()
                subprocess.run(['git', 'init', '-q', str(path)], check=True)
            (project / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/bootstrap.sh', project / 'scripts/bootstrap.sh')
            env = {**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}
            before = (other / '.git/config').read_bytes()
            for _ in range(2):
                result = subprocess.run(['bash', str(project / 'scripts/bootstrap.sh')], cwd=other,
                                        env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((other / '.git/config').read_bytes(), before)
            state_file = project / '.agy-factory/state/owned-resources.json'
            self.assertNotIn('control_plane', json.loads(state_file.read_text()))
            client = mock.Mock(control_plane={'workspace_id': 'observed', 'pane_id': 'observed:p1'})
            manager = factory.ResourceManager(client, state_file)
            self.assertEqual(manager.state['control_plane'], client.control_plane)
            self.assertEqual(manager.state['owned']['workspace_ids'], [])

    def test_status_projection_uses_current_engine_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with mock.patch.multiple(factory, PROJECT_ROOT=root, RUNS_DIR=root / 'runs',
                                     OWNED_RESOURCES_PATH=root / 'owned.json'):
                projection = factory.generate_status_projection()
            self.assertEqual(projection['factory_version'], factory.FACTORY_ENGINE_VERSION)

    def test_herdr_default_uses_path_and_respects_explicit_override(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(factory.shutil, 'which', return_value=None):
            client = factory.HerdrClient(pathlib.Path('/example/project'))
            self.assertEqual(client.herdr_bin, 'herdr')
            self.assertEqual(client.control_plane['workspace_id'], 'unknown')
            self.assertNotEqual(client.control_plane['herdr_socket'], '/root/.config/herdr/herdr.sock')
        with mock.patch.dict(os.environ, {'HERDR_BIN_PATH': '/explicit/missing/herdr', 'HERDR_SOCKET_PATH': '/explicit/socket'}, clear=True):
            client = factory.HerdrClient(pathlib.Path('/example/project'))
            self.assertEqual(client.herdr_bin, '/explicit/missing/herdr')
            self.assertEqual(client.control_plane['herdr_socket'], '/explicit/socket')

    def test_adapter_defaults_use_path_and_preserve_explicit_commands(self):
        for adapter_type, default in ((factory.ClaudeAdapter, 'claude'), (factory.OpenCodeAdapter, 'opencode')):
            with self.subTest(adapter=default):
                adapter = adapter_type('worker', {}, mock.Mock(), mock.Mock())
                self.assertEqual(adapter.command, default)
                adapter = adapter_type('worker', {'command': '/explicit/worker'}, mock.Mock(), mock.Mock())
                self.assertEqual(adapter.command, '/explicit/worker')

    def test_local_environment_and_demo_databases_are_ignored_but_templates_are_not(self):
        paths = ['.env', '.env.local', 'miniboard.db', 'miniboard.db-wal',
                 'examples/minilinks/minilinks.db', 'examples/minilinks/minilinks.db-journal',
                 '.env.example', '.env.sample', 'fixtures/example.json']
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT,
                                input='\n'.join(paths)+'\n', text=True, capture_output=True, check=True)
        self.assertEqual(set(result.stdout.splitlines()), set(paths[:6]))

    def test_preflight_does_not_collect_host_config_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            client = mock.Mock(control_plane={})
            client.run_cmd.return_value = subprocess.CompletedProcess([], 0, stdout='test', stderr='')
            client.get_snapshot.return_value = {'result': {'snapshot': {'workspaces': [], 'panes': []}}}
            process = subprocess.CompletedProcess([], 0, stdout='test', stderr='')
            with mock.patch.multiple(factory, PROJECT_ROOT=root, EVIDENCE_DIR=root / 'evidence'), \
                    mock.patch.object(factory, 'HerdrClient', return_value=client), \
                    mock.patch.object(factory.subprocess, 'run', return_value=process):
                report = factory.run_preflight()
            self.assertEqual(report['config_files'], [])
            self.assertEqual(report['config_collection'], 'disabled')


class PersistenceMaintenanceTests(unittest.TestCase):
    def check_directory_fsync_failure(self, module, writer):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / 'state.json'
            real_close = os.close
            with mock.patch.object(module.os, 'fsync', side_effect=[None, OSError('unsupported directory fsync')]), \
                    mock.patch.object(module.os, 'close', wraps=real_close) as close, \
                    self.assertLogs('factory', level='WARNING') as messages:
                writer(target)
            self.assertEqual(json.loads(target.read_text()), {'value': 1})
            close.assert_called_once()
            self.assertIn('WARNING_DIRECTORY_FSYNC_FAILED', messages.output[0])

    def test_atomic_json_warns_and_closes_directory_after_fsync_failure(self):
        self.check_directory_fsync_failure(factory, lambda target: factory.atomic_write_json(target, {'value': 1}))

    def test_context_packet_warns_and_closes_directory_after_fsync_failure(self):
        packet = mock.Mock()
        packet.to_dict.return_value = {'value': 1}
        self.check_directory_fsync_failure(context, lambda target: context.save_context_packet(packet, target))

    def test_handoff_packet_warns_and_closes_directory_after_fsync_failure(self):
        packet = mock.Mock()
        packet.to_dict.return_value = {'value': 1}
        self.check_directory_fsync_failure(context, lambda target: context.save_handoff_packet(packet, target))


if __name__ == '__main__':
    unittest.main()
