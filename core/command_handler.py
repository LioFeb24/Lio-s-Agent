from core.instruction_loader import load_instruction_table


class CommandHandler:
    """负责指令表加载与指令分类。"""

    def __init__(self) -> None:
        self.instructions = load_instruction_table()

    def get_available_instructions(self):
        """返回当前可用指令列表。"""
        return sorted(self.instructions.keys())

    def classify(self, user_input: str):
        """判断输入是否为已知指令。"""
        if not user_input.startswith("/"):
            return {"kind": "chat"}
        if user_input == "/add":
            return {"kind": "session_add", "input": user_input}
        if user_input == "/endsession":
            return {"kind": "end_session", "input": user_input}
        if user_input == "/rmsession":
            return {"kind": "remove_session_missing_target", "input": user_input}
        if user_input.startswith("/rmsession "):
            session_id = user_input[len("/rmsession ") :].strip()
            if not session_id:
                return {"kind": "remove_session_missing_target", "input": user_input}
            return {"kind": "remove_session", "session_id": session_id, "input": user_input}
        if user_input == "/end":
            return {"kind": "deprecated_end", "input": user_input}
        if user_input == "/session":
            return {"kind": "session_missing_target", "input": user_input}
        if user_input == "/session list":
            return {"kind": "session_list", "input": user_input}
        if user_input == "/session new":
            return {"kind": "session_add", "input": user_input}
        if user_input.startswith("/session "):
            session_id = user_input[9:].strip()
            if not session_id:
                return {"kind": "session_missing_target", "input": user_input}
            if session_id == "list":
                return {"kind": "session_list", "input": user_input}
            if session_id == "new":
                return {"kind": "session_add", "input": user_input}
            return {"kind": "session_switch", "session_id": session_id, "input": user_input}
        if user_input == "/exec":
            return {"kind": "exec_missing_task", "input": user_input}
        if user_input.startswith("/exec "):
            task = user_input[6:].strip()
            if not task:
                return {"kind": "exec_missing_task", "input": user_input}
            return {"kind": "exec", "task": task, "input": user_input}
        if user_input == "/skill":
            return {"kind": "skill_missing_target", "input": user_input}
        if user_input == "/skill add":
            return {"kind": "skill_add", "input": user_input}
        if user_input == "/skill list":
            return {"kind": "skill_list", "input": user_input}
        if user_input.startswith("/skill "):
            payload = user_input[7:].strip()
            if not payload:
                return {"kind": "skill_missing_target", "input": user_input}
            parts = payload.split(maxsplit=1)
            skill_name = parts[0].strip()
            skill_args = parts[1].strip() if len(parts) > 1 else ""
            if skill_name == "add":
                return {"kind": "skill_add", "input": user_input}
            if skill_name == "list":
                return {"kind": "skill_list", "input": user_input}
            return {
                "kind": "skill_run",
                "skill_name": skill_name,
                "skill_args": skill_args,
                "input": user_input,
            }

        instruction = self.instructions.get(user_input)
        if instruction is None:
            return {"kind": "unknown_command", "input": user_input}
        if user_input == "/rm":
            return {"kind": "remove_records"}
        return {"kind": "known_command", "input": user_input, "instruction": instruction}
