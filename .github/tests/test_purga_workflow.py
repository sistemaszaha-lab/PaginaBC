"""Pruebas del shell real del workflow, sin red ni secretos (python -m unittest)."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import textwrap
import unittest


WORKFLOW = Path(__file__).parents[1] / 'workflows/purga-papelera.yml'


def script(step):
    section = WORKFLOW.read_text().split('- name: ' + step, 1)[1]
    section = section.split('run: |', 1)[1].split('\n      - name:', 1)[0]
    return textwrap.dedent(section)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        ssh = self.root / 'ssh'
        ssh.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE"\nexit "${REMOTE_EXIT:-0}"\n')
        ssh.chmod(0o700)
        self.env = dict(os.environ, PATH=str(self.root)+':'+os.environ['PATH'],
                        RUNNER_TEMP=str(self.root), GITHUB_STEP_SUMMARY=str(self.root/'summary'),
                        CAPTURE=str(self.root/'capture'), PURGA_ACTIVA='false',
                        PURGA_MODO='dry-run', RAILWAY_WEB_SSH_USER='test-target')

    def run_step(self, name='Verificar web y ejecutar purga'):
        return subprocess.run(['bash','-c',script(name)], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_simulacion_sin_activar_purga(self):
        self.assertEqual(self.run_step().returncode, 0)
        command = (self.root/'capture').read_text()
        self.assertIn('--dry-run', command)
        self.assertIn('RAILWAY_ENVIRONMENT_ID', command)
        self.assertIn('RAILWAY_SERVICE_ID', command)
        self.assertIn('StrictHostKeyChecking=yes', command)

    def test_purga_real_desactivada_falla_antes_de_ssh(self):
        self.env['PURGA_MODO']='real'
        self.assertNotEqual(self.run_step().returncode, 0)
        self.assertFalse((self.root/'capture').exists())

    def test_autenticacion_fallida_es_job_fallido(self):
        self.env['REMOTE_EXIT']='255'
        self.assertEqual(self.run_step().returncode, 255)
        self.assertIn('estado=fallo', (self.root/'summary').read_text())

    def test_error_comando_remoto_es_job_fallido(self):
        self.env['REMOTE_EXIT']='1'
        self.assertEqual(self.run_step().returncode, 1)
        self.assertIn('codigo=1', (self.root/'summary').read_text())

    def test_credenciales_ausentes_fallan(self):
        self.env.update(RAILWAY_SSH_PRIVATE_KEY='', RAILWAY_SSH_KNOWN_HOSTS='')
        self.assertNotEqual(self.run_step('Preparar acceso SSH').returncode, 0)

    def test_agenda_y_concurrencia(self):
        text=WORKFLOW.read_text()
        self.assertIn("cron: '0 9 * * *'", text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('timeout-minutes: 60', text)
        self.assertIn("github.event_name == 'schedule' && vars.PURGA_PAPELERA_ACTIVA == 'true'", text)


if __name__ == '__main__':
    unittest.main()
