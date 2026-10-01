# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""Check repository file attribution without installing licensing tools."""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT).decode('utf-8').split('\0')
    annotations = tomllib.loads((ROOT/'REUSE.toml').read_text(encoding='utf-8'))['annotations']
    declared = {}
    for entry in annotations:
        for name in entry['path']:
            if name in declared:
                raise ValueError(f'Duplicate licensing annotation: {name}')
            declared[name] = entry
    errors = []
    checked = 0
    for name in sorted(set(paths)-{''}):
        path = ROOT/name
        if not path.is_file() or name == 'LICENSE' or name.startswith('LICENSES/') or name == 'REUSE.toml':
            continue
        if name in declared:
            entry = declared[name]
            copyright_text = entry.get('SPDX-FileCopyrightText')
            license_id = entry.get('SPDX-License-Identifier')
        else:
            prefix = path.read_bytes()[:4096].decode('utf-8-sig', errors='replace')
            lines = prefix.splitlines()[:12]
            copyright_text = [line for line in lines if re.match(
                r'^\s*(?:#|//|/\*|\*|<!--)?\s*SPDX-FileCopyrightText:', line)]
            license_lines = [re.search(r'SPDX-License-Identifier:\s*(.*?)\s*(?:\*/|-->)?$', line)
                             for line in lines]
            license_id = next((m.group(1) for m in license_lines if m), None)
        if not copyright_text or not license_id:
            errors.append(f'{name}: missing copyright/license metadata')
            continue
        identifiers = re.findall(r'[A-Za-z0-9][A-Za-z0-9.+-]*', license_id)
        for identifier in identifiers:
            if identifier not in ('AND', 'OR', 'WITH') and not (ROOT/'LICENSES'/f'{identifier}.txt').is_file():
                errors.append(f'{name}: missing license text for {identifier}')
        checked += 1
    if (ROOT/'LICENSE').read_bytes() != (ROOT/'LICENSES/Apache-2.0.txt').read_bytes():
        errors.append('Apache license copies differ')
    for name in ('frontend/public/favicon.svg', 'frontend/public/icons.svg'):
        entry = declared.get(name, {})
        if entry.get('SPDX-License-Identifier') != 'MIT' or 'Vite contributors' not in str(entry.get('SPDX-FileCopyrightText')):
            errors.append(f'{name}: upstream MIT attribution must be retained')
    for name in declared:
        if not (ROOT/name).is_file():
            errors.append(f'Annotation refers to missing file: {name}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'PASS licensing coverage: {checked} files; license texts and upstream notices present')
    return 0


if __name__ == '__main__':
    sys.exit(main())
