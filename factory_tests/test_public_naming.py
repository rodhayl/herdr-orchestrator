"""Presentation naming must stay separate from stable runtime identifiers."""
from __future__ import annotations

import http.client
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

from tools import factory_ui

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = 'Herdr Orchestrator'


class PublicNamingTests(unittest.TestCase):
    def test_readme_and_catalog_identify_the_project_without_renaming_providers(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertEqual(readme.splitlines()[0], '# ' + BRAND)
        self.assertIn('AGY is one supported provider', readme)
        self.assertIn('`factory_tests/`', readme)
        config = json.loads((ROOT / 'factory.json').read_text())
        self.assertEqual(config['project_name'], BRAND)
        profiles = json.loads((ROOT / 'harness_profiles.json').read_text())
        self.assertIn(BRAND, profiles['description'])
        self.assertEqual(profiles['profiles']['agy-spec-high']['harness'], 'agy')
        self.assertEqual(profiles['profiles']['droid-backend-xhigh']['adapter'], 'droid')

    def test_cli_help_uses_public_brand_without_executing_providers(self):
        for script in ('tools/factory.py', 'tools/factory_ui.py', 'scripts/vendor_ui.py'):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, str(ROOT / script), '--help'], cwd=ROOT,
                                        env={**os.environ, 'FACTORY_PROVIDER_PROBES': '0'},
                                        text=True, capture_output=True, timeout=30, check=True)
                self.assertIn(BRAND, result.stdout)
                self.assertNotIn('AGY-Herdr Software Factory', result.stdout)
                self.assertNotIn('Factory Control UI', result.stdout)

    def test_served_brand_preserves_frontend_and_snapshot_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = pathlib.Path(tmp)
            server = factory_ui.make_server(project, '127.0.0.1', 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.request('GET', '/')
                response = conn.getresponse()
                page = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn('<title>' + BRAND + '</title>', page)
                self.assertIn('<strong>' + BRAND + '</strong>', page)
                self.assertIn('aria-hidden="true">HO</div>', page)
                self.assertIn('x-data="factoryControl"', page)
                self.assertIn('/assets/factory.css', page)
                conn.close()
                conn = http.client.HTTPConnection(host, port, timeout=5)
                conn.request('GET', '/api/v1/snapshot')
                response = conn.getresponse()
                snapshot = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(snapshot['api_version'], '1')
                self.assertIn('factory', snapshot)
                self.assertEqual(snapshot['factory']['project_root'], str(project.resolve()))
                self.assertEqual(server.read_model.runtime_root, project.resolve() / '.agy-factory')
                conn.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

    def test_current_public_docs_and_banners_do_not_restore_legacy_brand(self):
        paths = list(ROOT.glob('*.md')) + list((ROOT / 'docs').glob('*.md'))
        paths += list((ROOT / 'scripts').glob('*.sh'))
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text()
                self.assertNotIn('AGY-Herdr Software Factory', text)
                self.assertNotIn('Factory Control UI', text)
