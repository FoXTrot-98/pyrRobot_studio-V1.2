import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.runtime.plugin_builder import Builder, Draft, TestRequest, generate
from core.runtime.plugin_registry import PluginRegistry


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.builder = Builder(Path(self.temp.name) / 'tests')

    def tearDown(self):
        self.builder.close()
        self.temp.cleanup()

    def draft(self, **changes):
        data = dict(slug='test_builder', name='Test builder', template='processing',
                    inputs=[{'name':'input'}], outputs=[{'name':'output'}])
        return Draft(**(data | changes))

    def run_source(self, source, sample=None):
        started = self.builder.start(TestRequest(source=source, sample=sample or {'value': 7}, trusted=True))
        deadline = time.monotonic() + 12
        while self.builder.status(started['id'])['status'] == 'running':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.05)
        return self.builder.status(started['id'])

    def test_processing_test_install_and_no_overwrite(self):
        source = generate(self.draft())
        result = self.run_source(source)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['result']['outputs'][0]['payload'], {'value':7})
        destination = Path(self.temp.name) / 'installed'
        installed = self.builder.install(result['id'], PluginRegistry(), destination)
        self.assertEqual(Path(installed['path']).read_text(encoding='utf-8'), source)
        with self.assertRaises(FileExistsError): self.builder.install(result['id'], PluginRegistry(), destination)
        registry = PluginRegistry()
        registry.scan_directory(destination)
        self.assertIn('user.test_builder', registry)
        with self.assertRaises(ValueError): self.builder.install(result['id'], registry, destination)

    def test_sensor_and_typed_message_validation(self):
        source = generate(self.draft(template='sensor', inputs=[], sample={'value':3}))
        self.assertEqual(self.run_source(source)['status'], 'passed')
        typed = {'name':'command','schema':'pyrobot/VelocityCommand@1'}
        source = generate(self.draft(inputs=[typed], outputs=[typed]))
        result = self.run_source(source)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('ValidationError', result['result']['error'])
        valid = self.run_source(source, {'linear':0.0,'angular':0.0,'time':0.0})
        self.assertEqual(valid['status'], 'passed', valid)

    def test_invalid_generation_and_syntax(self):
        with self.assertRaises(ValueError): self.draft(slug='../escape')
        with self.assertRaises(ValueError): self.draft(outputs=[{'name':'same'},{'name':'same'}])
        with self.assertRaises(ValueError): self.draft(inputs=[{'name':'in','schema':'unknown'}])
        with self.assertRaises(Exception): generate(self.draft(params=[{'name':'rate','kind':'number','default':-1,'min':1}]))
        with self.assertRaises(SyntaxError): self.run_source('invalid python !!!')

    def test_timeout_cancel_and_failed_install(self):
        result = self.run_source('while True: pass')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('timed out', result['result']['error'])
        with self.assertRaises(ValueError): self.builder.install(result['id'], PluginRegistry())
        job = self.builder.start(TestRequest(source='while True: pass', trusted=True))
        self.assertEqual(self.builder.cancel(job['id'])['status'], 'cancelled')
        self.builder.jobs[job['id']]['process'].wait(timeout=3)


if __name__ == '__main__': unittest.main()
