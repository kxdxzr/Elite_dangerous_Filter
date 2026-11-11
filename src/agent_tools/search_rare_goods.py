"""Search rare-goods destinations; pass JSON arguments on stdin."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tool import main

if __name__ == '__main__':
    raise SystemExit(main('search_rare_goods'))
