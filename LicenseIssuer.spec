from PyInstaller.utils.hooks import collect_all

ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all('customtkinter')

a = Analysis(
    ['packaging\\license_issuer_entry.py'],
    pathex=['.'],
    binaries=ctk_binaries,
    datas=ctk_datas + [('seller_private_key.json', '.')],
    hiddenimports=[
        'license_issuer_gui',
        'novel_writer',
        'novel_writer.license',
        'tkinter',
        'tkinter.messagebox',
    ] + ctk_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'pydoc',
        'doctest',
        'lib2to3',
        'numpy',
        'pandas',
        'matplotlib',
        'PIL',
        'cv2',
        'scipy',
        'sympy',
        'IPython',
        'notebook',
        'jupyter',
        'pygments',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='XiaomiAILicenseIssuer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
