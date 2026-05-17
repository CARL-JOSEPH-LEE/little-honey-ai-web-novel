



from PyInstaller.utils.hooks import collect_all

ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all('customtkinter')


a = Analysis(
    ['packaging\\windows_desktop_entry.py'],
    pathex=['.'],
    binaries=ctk_binaries,
    datas=ctk_datas,
    hiddenimports=[
        'gui',
        'license_manager',
        'novel_engine',
        'novel_project',
        'novel_writer',
        'novel_writer.config',
        'novel_writer.context',
        'novel_writer.deepseek_client',
        'novel_writer.errors',
        'novel_writer.license',
        'novel_writer.license_admin',
        'novel_writer.pipeline',
        'novel_writer.prompts',
        'novel_writer.state',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'http.server',
        'urllib.request',
        'urllib.error',
        'urllib.parse',
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
    name='XiaomiAINovel',
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
