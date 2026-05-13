from core.constants import INSTRUCTION_PATH
from core.file_utils import load_json


def collect_instruction_entries(node, table):
    """递归提取任意层级中的 instruction 字段，构造成指令查找表。"""
    if isinstance(node, dict):
        instruction = node.get("instruction")
        if isinstance(instruction, str):
            table[instruction] = node
        for value in node.values():
            collect_instruction_entries(value, table)
    elif isinstance(node, list):
        for item in node:
            collect_instruction_entries(item, table)


def load_instruction_table():
    """从 instruction.json 中加载全部可用指令。"""
    raw = load_json(INSTRUCTION_PATH, {})
    table = {}
    collect_instruction_entries(raw, table)
    return table
