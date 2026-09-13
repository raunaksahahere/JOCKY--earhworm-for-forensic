# Run on the target OS. One-directory output includes runtime and resources.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
import sys
root = Path(SPECPATH).parent
name = 'JOCKY-backend' if sys.platform == 'win32' else 'jocky-backend'
a = Analysis([str(root / 'backend' / 'entry.py')], pathex=[str(root)],
             datas=[(str(root / 'compiler' / 'grammar.lark'), 'compiler'),
                    (str(root / 'assets' / 'fonts'), 'assets/fonts')],
             hiddenimports=collect_submodules('reportlab') + collect_submodules('uharfbuzz'),
             excludes=['tkinter', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=name, debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
