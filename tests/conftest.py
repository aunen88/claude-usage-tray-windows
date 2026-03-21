import sys
import pathlib
# Add project root to sys.path so bare `import api` etc. work from any cwd
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
