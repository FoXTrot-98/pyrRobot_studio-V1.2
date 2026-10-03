# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Qualification reports must retain failed repeats without overwriting results."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parent))
import webots_matrix


class MatrixTests(unittest.TestCase):
    def test_repeat_retains_failure_and_success_and_passes_exploration_options(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cases=root/'cases.json'
            cases.write_text(json.dumps([dict(name='explore',explore_seconds=12,
                spawn=[1,2,3],spawn_height=.1)]),encoding='utf-8-sig')
            commands=[]
            def run(command,**kwargs):
                commands.append(command)
                output=Path(command[command.index('--output')+1])
                if len(commands)==1:
                    output.with_suffix('.failure.json').write_text('{}')
                    return SimpleNamespace(returncode=1)
                output.write_text('{"home_error":0.1}')
                return SimpleNamespace(returncode=0)
            with patch.object(sys,'argv',['matrix','--cases',str(cases),'--output',str(root/'out'),'--repeat','2']),patch.object(webots_matrix.subprocess,'run',side_effect=run):
                self.assertEqual(webots_matrix.main(),1)
            results=json.loads(next((root/'out').glob('*/summary.json')).read_text())
            self.assertEqual([row['passed'] for row in results],[False,True])
            self.assertEqual([row['repeat'] for row in results],[1,2])
            self.assertIsNotNone(results[0]['diagnostic'])
            self.assertIsNone(results[0]['measurements'])
            self.assertEqual(results[1]['measurements']['home_error'],.1)
            self.assertNotEqual(results[0]['log'],results[1]['log'])
            self.assertIn('--explore-seconds',commands[0])
            self.assertIn('--spawn-height',commands[0])


if __name__=='__main__':unittest.main()
