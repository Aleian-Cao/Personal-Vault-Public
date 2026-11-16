"""Build an IMMUTABLE desktop candidate with provenance (Windows).

  python build_candidate.py [--suffix r2]

Outputs (never overwrites dist-desktop/, dist-desktop-e2e/ or any existing candidate; aborts if the target exists):
  dist-candidates/<BUILD_ID>/                PersonalVault.exe, pvault-sidecar.exe, provenance.json, SHA256SUMS.txt
  dist-candidates/<BUILD_ID>-experimental/   same exe + experimental sidecar (Qwen allowed, still needs PVAULT_QWEN=1)
BUILD_ID = PV-<utc date>-<first 8 hex of the source-tree hash>[-suffix]. All files are marked read-only afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
SOURCES = [
    ('sidecar', ['*.py', 'tests/*.py']),
    ('PersonalVault_MVP/personal_vault', ['*.py']),
    ('PersonalVault_MVP/tests', ['*.py']),
    ('web/src', ['**/*']),
    ('web/src-tauri/src', ['*.rs']),
    ('web/src-tauri/capabilities', ['*.json']),
    ('web/tests', ['*.mjs']),
    ('web/e2e', ['*.mjs', '*.ps1', '*.py']),
    ('evals', ['*.py', 'fixtures/*.json']),
    ('.', ['pvault-sidecar.spec', 'pvault-sidecar-exp.spec', 'build_candidate.py']),
]
SINGLE = ['web/index.html', 'web/package.json', 'web/package-lock.json', 'web/src-tauri/Cargo.toml', 'web/src-tauri/Cargo.lock',
          'web/src-tauri/tauri.conf.json', 'web/tailwind.config.js', 'web/vite.config.ts']


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest().upper()


def run(cmd, **kw):
    print('>', cmd if isinstance(cmd, str) else ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def out(cmd, **kw) -> str:
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw).stdout.strip().splitlines()[0]
    except Exception as e:  # noqa: BLE001
        return f'unavailable: {e}'


def source_manifest() -> dict:
    files = {}
    for base, pats in SOURCES:
        for pat in pats:
            for p in (ROOT / base).glob(pat):
                if p.is_file() and '__pycache__' not in p.parts and 'node_modules' not in p.parts:
                    files[p.relative_to(ROOT).as_posix()] = sha(p)
    for rel in SINGLE:
        if (ROOT / rel).is_file():
            files[rel] = sha(ROOT / rel)
    return dict(sorted(files.items()))


def lock_readonly(d: Path) -> None:
    for p in d.rglob('*'):
        if p.is_file():
            os.chmod(p, stat.S_IREAD)


def sidecar_probe(exe: Path, qwen_env: bool) -> dict:
    """Start the sidecar over stdio only, ask for startup_state after opening the demo; never runs inference."""
    tmp = tempfile.mkdtemp()
    env = {**os.environ, 'LOCALAPPDATA': tmp, 'HOME': tmp, 'USERPROFILE': tmp}
    if qwen_env:
        env['PVAULT_QWEN'] = '1'
    p = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env)
    try:
        p.stdout.readline()
        def rpc(i, m, **k):
            p.stdin.write(json.dumps({'id': i, 'method': m, 'params': k}) + '\n'); p.stdin.flush()
            return json.loads(p.stdout.readline())
        rpc(1, 'open_demo')
        st = rpc(2, 'startup_state')['result']
        private = rpc(3, '_require_unlocked')  # must be rejected by the allowlist
        return {'qwen_env_set': qwen_env, 'startup_state_qwen': st.get('qwen'), 'private_method_rejected': 'error' in private}
    finally:
        p.kill(); p.wait(); p.stdin.close(); p.stdout.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--suffix', default='')
    a = ap.parse_args()

    manifest = source_manifest()
    tree_hash = hashlib.sha256('\n'.join(f'{k} {v}' for k, v in manifest.items()).encode()).hexdigest().upper()
    utc = datetime.now(timezone.utc)
    build_id = f"PV-{utc:%Y%m%d}-{tree_hash[:8]}" + (f'-{a.suffix}' if a.suffix else '')
    cand = ROOT / 'dist-candidates' / build_id
    exp = ROOT / 'dist-candidates' / f'{build_id}-experimental'
    if cand.exists() or exp.exists():
        print(f'REFUSING: {cand} already exists (candidates are immutable)', file=sys.stderr)
        return 2
    cand.mkdir(parents=True)
    exp.mkdir(parents=True)

    parents = {}
    for d in ('dist-desktop', 'dist-desktop-e2e'):
        for f in sorted((ROOT / d).glob('*.exe')) if (ROOT / d).exists() else []:
            parents[f'{d}/{f.name}'] = {'sha256': sha(f), 'bytes': f.stat().st_size}

    work = ROOT / 'build' / build_id
    sc_dir = work / 'sidecar_out'
    run([sys.executable, '-m', 'PyInstaller', 'pvault-sidecar.spec', '--noconfirm', '--distpath', str(sc_dir), '--workpath', str(work / 'pi-release')], cwd=ROOT)
    run([sys.executable, '-m', 'PyInstaller', 'pvault-sidecar-exp.spec', '--noconfirm', '--distpath', str(sc_dir), '--workpath', str(work / 'pi-exp')], cwd=ROOT)
    shutil.copy(sc_dir / 'pvault-sidecar.exe', WEB / 'src-tauri' / 'bin' / 'pvault-sidecar-x86_64-pc-windows-msvc.exe')  # tauri build input
    run('npx tauri build --no-bundle', cwd=WEB, shell=True)

    shutil.copy(WEB / 'src-tauri' / 'target' / 'release' / 'app.exe', cand / 'PersonalVault.exe')
    shutil.copy(sc_dir / 'pvault-sidecar.exe', cand / 'pvault-sidecar.exe')
    shutil.copy(cand / 'PersonalVault.exe', exp / 'PersonalVault.exe')
    shutil.copy(sc_dir / 'pvault-sidecar-exp.exe', exp / 'pvault-sidecar.exe')  # the app looks for this name next to itself
    (exp / 'README_EXPERIMENTAL.txt').write_text(
        'EXPERIMENTAL build: Qwen can be enabled (set PVAULT_QWEN=1, PVAULT_MODEL_PATH, PVAULT_LLAMA_DIR). Not for release or distribution.\n'
        'The GGUF is never bundled. The llama-cli backend used by a frozen sidecar opens loopback sockets (see Wave Digest).\n', encoding='utf-8')

    config = json.loads((WEB / 'src-tauri' / 'tauri.conf.json').read_text(encoding='utf-8'))
    provenance = {
        'build_id': build_id,
        'built_utc': utc.isoformat(),
        'host': {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version()},
        'tools': {'rustc': out('rustc --version'), 'cargo': out('cargo --version'), 'node': out('node --version'), 'npm': out('npm --version'),
                  'tauri_cli': out('npx tauri --version', cwd=WEB), 'pyinstaller': out([sys.executable, '-m', 'PyInstaller', '--version'])},
        'source_tree_sha256': tree_hash,
        'source_files': len(manifest),
        'source_manifest': manifest,
        'cargo_lock_sha256': manifest.get('web/src-tauri/Cargo.lock'),
        'release_config': {'csp': config['app']['security']['csp'], 'window_browser_args': [w.get('additionalBrowserArgs') for w in config['app']['windows']],
                           'windows': [w['label'] for w in config['app']['windows']]},
        'commands': ['python -m PyInstaller pvault-sidecar.spec', 'python -m PyInstaller pvault-sidecar-exp.spec', 'npx tauri build --no-bundle'],
        'parent_artifacts_unchanged_baseline': parents,
        'outputs': {},
        'qwen': {'release_sidecar_QWEN_ALLOWED': False, 'gguf_embedded': False},
        'signing': 'NOT SIGNED',
    }
    for d in (cand, exp):
        for f in sorted(d.glob('*.exe')):
            provenance['outputs'][f'{d.name}/{f.name}'] = {'sha256': sha(f), 'bytes': f.stat().st_size}
    provenance['sidecar_probe'] = {'release_with_env': sidecar_probe(cand / 'pvault-sidecar.exe', True),
                                   'experimental_with_env': sidecar_probe(exp / 'pvault-sidecar.exe', True)}
    for d in (cand, exp):
        (d / 'provenance.json').write_text(json.dumps(provenance, indent=1, ensure_ascii=False), encoding='utf-8')
        sums = [f'{sha(f)}  {f.name}' for f in sorted(d.glob('*.exe'))] + [f'{sha(d / "provenance.json")}  provenance.json']
        (d / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
        lock_readonly(d)
    print(json.dumps({'build_id': build_id, 'dir': str(cand), 'outputs': provenance['outputs'], 'probe': provenance['sidecar_probe']}, indent=1))
    ok = (provenance['sidecar_probe']['release_with_env']['startup_state_qwen'] is False
          and provenance['sidecar_probe']['experimental_with_env']['startup_state_qwen'] is True
          and provenance['sidecar_probe']['release_with_env']['private_method_rejected'])
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main())
