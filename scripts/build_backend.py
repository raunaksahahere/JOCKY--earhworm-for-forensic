"""Native backend freezer. Run with the development virtualenv on each target OS."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                '--distpath', str(root / 'backend-dist'), '--workpath', str(root / 'build' / 'pyinstaller'),
                str(root / 'packaging' / 'backend.spec')], cwd=root, check=True)
