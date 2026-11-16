# -*- mode: python ; coding: utf-8 -*-
# EXPERIMENTAL sidecar (Qwen may be enabled with PVAULT_QWEN=1). Never part of the release candidate.
# Differs from pvault-sidecar.spec only in the entry point (sets QWEN_ALLOWED) and the output name.


a = Analysis(
    ['sidecar/sidecar_experimental.py'],
    pathex=['sidecar', 'PersonalVault_MVP'],
    binaries=[],
    datas=[],
    hiddenimports=['sidecar_server', 'chat_pipeline', 'qwen_runner'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pvault-sidecar-exp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
