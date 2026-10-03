# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Sequential live Webots qualification; retain every case's report and log."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',type=Path,default=ROOT/'tests/fixtures/webots-matrix.json')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/qualification')
    parser.add_argument('--repeat',type=int,default=1)
    args=parser.parse_args()
    if args.repeat<1:parser.error('--repeat must be positive')
    cases=json.loads(args.cases.read_text(encoding='utf-8-sig'))
    cases=[(repeat+1,case) for repeat in range(args.repeat) for case in cases]
    directory=args.output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory.mkdir(parents=True)
    results=[]
    for index,(repeat,case) in enumerate(cases):
        report=directory/f'{index:02d}.json'
        log=directory/f'{index:02d}.log'
        command=[sys.executable,str(ROOT/'tests/webots_smoke.py'),'--return-home','--output',str(report.resolve())]
        for key in ('project','world','planner','controller','spawn_height','explore_seconds'):
            if key in case:command.extend(['--'+key.replace('_','-'),str(case[key])])
        if case.get('finish_exploration'):command.append('--finish-exploration')
        if 'spawn' in case:command.extend(['--spawn',*map(str,case['spawn'])])
        print(f"Running {case['name']} (repeat {repeat})",flush=True)
        # Smoke has bounded stage waits and owns/cleans its Webots process.
        # Do not kill only the parent on timeout and leave a simulator orphaned.
        with log.open('w',encoding='utf-8') as stream:
            process=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        result=dict(name=case['name'],repeat=repeat,case=case,passed=process.returncode==0,
                    exit_code=process.returncode,log=log.name,
                    diagnostic=report.with_suffix('.failure.json').name if report.with_suffix('.failure.json').exists() else None,
                    measurements=json.loads(report.read_text()) if report.exists() else None)
        results.append(result)
        (directory/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(f"{'PASS' if result['passed'] else 'FAIL'} {case['name']} ({log})",flush=True)
    print(f'Report: {directory / "summary.json"}',flush=True)
    return int(not results or any(not result['passed'] for result in results))


if __name__=='__main__':sys.exit(main())
