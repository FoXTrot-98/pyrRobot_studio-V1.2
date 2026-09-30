"""Inspect and adapt local Webots worlds without modifying their source files.

Supports ENU worlds, native nodes, installed Webots PROTOs and simple local
PROTOs. Unknown remote/custom template PROTOs are rejected, not guessed.
"""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from core.simulation.webots_examples import webots_home

TOKEN = re.compile(r'#[^\n]*|"(?:\\.|[^"\\])*"|[{}\[\]]|[^\s{}\[\]",]+')

def tokens(source):
    return [m for m in TOKEN.finditer(source) if not m.group().startswith('#')]

def without_comments(source):
    return TOKEN.sub(lambda m: ' '*len(m.group()) if m.group().startswith('#') else m.group(),source)


def blocks(source):
    ts=tokens(source); stack=[]; result=[]
    for i,t in enumerate(ts):
        if t.group() in ('{','['): stack.append(i)
        elif t.group() in ('}',']'):
            if not stack or ts[stack[-1]].group()!=('{' if t.group()=='}' else '['):
                raise ValueError('Unbalanced brackets in Webots world')
            start=stack.pop()
            if t.group()=='}':
                kind=ts[start-1].group() if start else ''
                first=start-1
                if start>=3 and ts[start-3].group()=='DEF':first=start-3
                result.append((kind,ts[first].start(),t.end(),not stack,ts[start].end(),t.start()))
    if stack:raise ValueError('Unclosed bracket in Webots world')
    return sorted(result,key=lambda item:item[1])

def read(path):
    path=Path(path).expanduser().resolve()
    if path.suffix.lower() not in ('.wbt','.proto') or not path.is_file():
        raise ValueError('Select an existing .wbt world on the backend computer')
    if path.stat().st_size>8*1024*1024:raise ValueError('World/PROTO exceeds 8 MiB')
    return path,path.read_text(encoding='utf-8-sig')

def inspect(path, executable=''):
    path,source=read(path)
    if path.suffix.lower()!='.wbt' or not source.startswith('#VRML_SIM R2025'):
        raise ValueError('Use a Webots R2025 world; convert older worlds in Webots before importing')
    home=webots_home(executable)
    library={p.findtext('url'):(p.findtext('name'),p.findtext('base-type')) for p in ET.parse(home/'resources/proto-list.xml').getroot()}
    native={p.stem for p in (home/'resources/nodes').glob('*.wrl')}
    dependencies=[]; types={name:name for name in native}; extern_edits=[]
    visiting=set()

    def load_types(text,base):
        matches=list(re.finditer(r'\bEXTERNPROTO\s+"([^"\n]+)"',without_comments(text)))
        # Inline definitions and fallback URL lists need a full PROTO compiler.
        clean=' '.join(t.group() for t in tokens(text))
        if re.search(r'\bEXTERNPROTO\s*\[',clean):raise ValueError('EXTERNPROTO fallback lists are not supported; use one resolved URL')
        for m in matches:
            url=m.group(1)
            if url in library:
                name,kind=library[url];types[name]=kind
            elif url.startswith('webots://'):
                remote='https://raw.githubusercontent.com/cyberbotics/webots/R2025a/'+url[len('webots://'):]
                if remote not in library:raise ValueError(f'Unknown installed Webots PROTO: {url}')
                name,kind=library[remote];types[name]=kind
            elif '://' in url:
                raise ValueError(f'Unrecognized remote PROTO: {url}. Use a local supported PROTO or the installed Webots version')
            else:
                local=(base/url).resolve()
                if local in visiting:raise ValueError('Cyclic local PROTO dependency')
                visiting.add(local)
                _,proto=read(local)
                if '%<' in proto:raise ValueError(f'Custom template PROTO requires manual compatibility review: {local.name}')
                load_types(proto,local.parent)
                pt=tokens(proto)
                name=next((pt[i+1].group() for i,t in enumerate(pt[:-1]) if t.group()=='PROTO'),None)
                roots=[b for b in blocks(proto) if b[3]]
                if not name or not roots:raise ValueError(f'Cannot classify PROTO {local.name}')
                body=proto[roots[-1][4]:roots[-1][5]]
                children=[b for b in blocks(body) if b[3]]
                if len(children)!=1 or children[0][0] not in types:raise ValueError(f'Unsupported PROTO root: {local.name}')
                kind=types[children[0][0]]
                if kind!='Robot' and any(types.get(b[0])=='Robot' for b in blocks(body)):
                    raise ValueError('Nested robots inside environment PROTOs are not supported')
                types[name]=kind;dependencies.append(str(local));visiting.remove(local)
            if base==path.parent and text is source:
                extern_edits.append((m.start(),m.end(),name,kind))

    load_types(source,path.parent)
    ts=tokens(source)
    if any(t.group() in ('PROTO','IMPORT','EXPORT') for t in ts):raise ValueError('Inline PROTO/IMPORT/EXPORT worlds are not supported')
    all_blocks=blocks(source); removed=[]; edits=[]; removed_defs=[]
    top=[b for b in all_blocks if b[3]]
    infos=[b for b in top if b[0]=='WorldInfo']
    if len(infos)!=1:raise ValueError('World requires exactly one WorldInfo node')
    for kind,start,end,is_top,_,_ in all_blocks:
        if kind not in types:raise ValueError(f'Unrecognized world node or PROTO: {kind}')
        if types[kind]=='Robot':
            if not is_top:raise ValueError('Nested robots are not supported; move them to top level in Webots first')
            removed.append(kind);edits.append((start,end,''))
            match=re.match(r'DEF\s+(\S+)',source[start:end])
            if match:removed_defs.append(match.group(1))
    clean=' '.join(t.group() for t in ts)
    if re.search(r'\bDEF\s+PYROBOT\b',clean):raise ValueError('World reserves DEF PYROBOT; rename that node before importing')
    for name in removed_defs:
        if re.search(r'\bUSE\s+'+re.escape(name)+r'\b',clean):raise ValueError('World reuses a robot DEF; detach those references before importing')
    info=infos[0]; body=without_comments(source[info[4]:info[5]])
    coordinate=re.search(r'\bcoordinateSystem\s+"([^"]+)"',body)
    if coordinate and coordinate.group(1)!='ENU':raise ValueError('Only ENU (Z-up) worlds are supported; convert the world in Webots first')
    physics=re.search(r'\bphysics\s+"([^"]+)"',body)
    if physics and physics.group(1) not in ('','<none>'):raise ValueError('World physics plugins are not supported')
    body=re.sub(r'\bbasicTimeStep\s+[\d.]+','',body)
    edits.append((info[4],info[5],'\n basicTimeStep 20\n'+body))
    for start,end,name,kind in extern_edits:
        if kind=='Robot':edits.append((start,end,''))
    for start,end,replacement in sorted(edits,reverse=True):source=source[:start]+replacement+source[end:]
    # Resolve relative asset/PROTO URLs against the source world, not the new run
    # directory. Referenced files remain read-only; the world itself is copied.
    def absolute(m):
        value=json.loads(m.group())
        if not value or '://' in value:return m.group()
        candidate=(path.parent/value).resolve()
        if candidate.is_file():return json.dumps(candidate.as_posix())
        if Path(value).suffix.lower() in ('.proto','.obj','.stl','.dae','.png','.jpg','.jpeg','.hdr','.exr','.wrl'):
            raise ValueError(f'Missing local world asset: {value}')
        return m.group()
    source=TOKEN.sub(lambda m: absolute(m) if m.group().startswith(chr(34)) else m.group(),source)
    source=wheel_contacts(source, dependencies)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'removed_robots':removed,
            'dependencies':dependencies,'source':source,
            'warnings':['Spawn floor height and clearance must be checked in Webots. Slopes, stairs and dynamic scenes are not qualified for this planar navigator.',
                        'Remote Webots assets may need network/cache access. Local referenced assets must stay available.',
                        'Studio adds approximate skid-steer wheel contacts for default/floor and explicitly named materials (friction 0.8, force-dependent slip 0.02).']}

def available(executable=''):
    home=webots_home(executable)
    paths=sorted((home/'projects').rglob('*.wbt'))
    # Environment demos first; all installed worlds remain selectable and must
    # pass inspection before application.
    paths.sort(key=lambda p:('samples/environments/' not in p.as_posix(),p.as_posix()))
    return [{'path':str(p),'name':p.relative_to(home/'projects').as_posix()} for p in paths]

def wheel_contacts(source, dependencies=()):
    """Add Studio's skid-steer approximation only for its own wheel material.

    A source world usually has no contact rule for our four-wheel chassis.
    Zero force-dependent slip can lock it in turns while encoders predict
    rotation. Preserve the world's other contacts and its original file.
    """
    material = 'pyrobot_studio_wheel'
    texts = [without_comments(source)] + [without_comments(read(p)[1]) for p in dependencies]
    materials = {'default', 'floor'}
    for text in texts:
        materials.update(re.findall(r'\b(?:contactMaterial|material1|material2)\s+"([^"\n]+)"', text))
    if material in materials:
        raise ValueError('World uses reserved contact material pyrobot_studio_wheel; rename it before importing')
    pairs = '\n'.join(f'ContactProperties {{ material1 "{material}" material2 {json.dumps(name)} '
                      'coulombFriction [ 0.8 ] forceDependentSlip [ 0.02 ] }' for name in sorted(materials))
    info = next(b for b in blocks(source) if b[0]=='WorldInfo' and b[3])
    body = source[info[4]:info[5]]
    ts = tokens(body)
    field = next((i for i,t in enumerate(ts) if t.group()=='contactProperties'), None)
    if field is None:
        body += '\n contactProperties [ '+pairs+' ]\n'
    else:
        if field+1 >= len(ts) or ts[field+1].group()!='[':
            raise ValueError('World contactProperties must be an explicit list')
        offset = ts[field+1].end()
        body = body[:offset]+'\n'+pairs+'\n'+body[offset:]
    return source[:info[4]]+body+source[info[5]:]


def compose(path,generated,executable='',expected_hash=''):
    info=inspect(path,executable)
    if expected_hash and info['sha256']!=expected_hash:raise ValueError('Source world changed. Check and apply it again in World setup')
    robot=next(b for b in blocks(generated) if b[0]=='Robot' and b[3])
    body = generated[robot[1]:robot[2]].replace('contactMaterial "wheel"', 'contactMaterial "pyrobot_studio_wheel"')
    return info['source']+'\n'+body+'\n'
