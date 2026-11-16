"""Build QA variants of the desktop exe that differ ONLY in WebView2 browser arguments, then profile each.
Usage (from web/): python e2e/mem_variants.py
Writes ../artifacts/hardening/memory_profile_<variant>.json and variants_summary.json.
Never touches dist-desktop/ or dist-desktop-e2e/ (baseline artifacts); variants live in ../dist-variants/.
"""
import json
import os
import shutil
import subprocess
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(WEB)
BASE_FEATURES = 'msWebOOUI,msPdfOOUI,msSmartScreenProtection'
COMMON = '--disable-background-networking --disable-component-update --disable-domain-reliability --disable-sync --no-pings --disable-breakpad'
DEBUG = '--remote-debugging-port=9333'

VARIANTS = {
    'v0-control': '',
    'v1-no-gpu': '--disable-gpu',
    'v2-no-gpu-1renderer': '--disable-gpu --renderer-process-limit=1',
    'v3-1renderer': '--renderer-process-limit=1',
    'v4-no-gpu-1renderer-netinproc': '--disable-gpu --renderer-process-limit=1 --enable-features=NetworkServiceInProcess2',
    'v5-lean': '--disable-gpu --renderer-process-limit=1 --enable-features=NetworkServiceInProcess2 --disable-features=StorageServiceOutOfProcess',
}


def conf_for(extra: str) -> dict:
    base = json.load(open(os.path.join(WEB, 'src-tauri', 'tauri.conf.json'), encoding='utf-8'))
    feats = f'--disable-features={BASE_FEATURES}'
    if '--disable-features=' in extra:  # merge into the single disable-features flag
        more = extra.split('--disable-features=')[1].split()[0]
        extra = extra.replace(f'--disable-features={more}', '')
        feats = f'--disable-features={BASE_FEATURES},{more}'
    args = ' '.join(x for x in (feats, COMMON, extra.strip(), DEBUG) if x)
    return {'app': {'windows': [dict(w, additionalBrowserArgs=args) for w in base['app']['windows']]}}


def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, check=True, **kw)


def main():
    only = sys.argv[1:]  # optional variant names
    out_dir = os.path.join(ROOT, 'dist-variants')
    os.makedirs(out_dir, exist_ok=True)
    art = os.path.join(ROOT, 'artifacts', 'hardening')
    summary = {}
    for name, extra in VARIANTS.items():
        if only and name not in only:
            continue
        conf_path = os.path.join(WEB, 'e2e', f'.variant_{name}.json')
        json.dump(conf_for(extra), open(conf_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        print(f'=== build {name}: {extra or "(control)"}', flush=True)
        run(f'npx tauri build --no-bundle --config "{conf_path}"', cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        vdir = os.path.join(out_dir, name)
        os.makedirs(vdir, exist_ok=True)
        shutil.copy(os.path.join(WEB, 'src-tauri', 'target', 'release', 'app.exe'), os.path.join(vdir, 'PersonalVault-var.exe'))
        shutil.copy(os.path.join(ROOT, 'dist-desktop-e2e', 'pvault-sidecar.exe'), os.path.join(vdir, 'pvault-sidecar.exe'))
        os.remove(conf_path)
        subprocess.run('powershell -NoProfile -Command "Get-Process PersonalVault-var,pvault-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force"', shell=True)
        run(f'node e2e/profile_mem.mjs --exe "{os.path.join(vdir, "PersonalVault-var.exe")}" --label {name} --out "{art}" --fast 1', cwd=WEB)
        rep = json.load(open(os.path.join(art, f'memory_profile_{name}.json'), encoding='utf-8'))
        summary[name] = {s['state']: {'wsMB': s['wsMB'], 'privateMB': s['privateMB'], 'wsPrivateMB': s['wsPrivateMB'], 'procs': s['processes']} for s in rep['samples']}
    json.dump(summary, open(os.path.join(art, 'variants_summary.json'), 'w', encoding='utf-8'), indent=1)
    for n, st in summary.items():
        for state in ('3 unlocked, chat (20 entries)',):
            v = st.get(state)
            if v:
                print(f"{n:34s} procs={v['procs']:2d} WS={v['wsMB']:6.1f} Private={v['privateMB']:6.1f} PrivateWS={v['wsPrivateMB']:6.1f}")


if __name__ == '__main__':
    main()
