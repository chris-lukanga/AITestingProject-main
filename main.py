"""Root CLI shim preserves python main.py example.json."""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'backend'))
if len(sys.argv) == 2 and sys.argv[1] == 'example.json' and not (ROOT / 'example.json').exists():
    sys.argv[1] = str(ROOT / 'backend' / 'example.json')
runpy.run_path(str(ROOT / 'backend' / 'main.py'), run_name='__main__')
