"""会话JSON读写；原子替换避免异常中断时留下半个文件。"""
import json
from file_io import atomic_write


def load(path):
    try:
        with open(path, encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save(path, state):
    atomic_write(path, json.dumps(state, ensure_ascii=False, indent=1).encode('utf-8'))
