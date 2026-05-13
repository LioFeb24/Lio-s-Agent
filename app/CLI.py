import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runtime import AgentRuntime
from core.prompt_builder import style_reasoning_text


def print_session_history(runtime: AgentRuntime):
    """按顺序打印当前 session 的完整历史消息。"""
    history = runtime.get_current_history()
    if not history:
        print("当前会话暂无历史消息。")
        return

    for item in history:
        prefix = "你" if item.get("role") == "user" else "AI"
        print(f"{prefix}：{item.get('content', '')}")


def main():
    """终端交互入口，保持原有 CLI 使用方式不变。"""
    runtime = AgentRuntime()
    info = runtime.get_runtime_info()

    print(f"欢迎，{info['user']}。")
    if info["restored"]:
        print(f"检测到未结束会话，已恢复。开始时间：{info['start_time']}")
    else:
        print(f"新会话已开始。开始时间：{info['start_time']}")

    if info["instructions"]:
        print("可用指令：" + "、".join(info["instructions"]))
    print("内置命令：/session、/add、/endsession、/rmsession、/exec、/skill add、/skill")

    try:
        while True:
            user_input = input("你：").strip()
            if not user_input:
                continue

            command_info = runtime.classify_instruction(user_input)
            if command_info["kind"] == "unknown_command":
                print("未知指令")
                continue
            if command_info["kind"] == "deprecated_end":
                print("/end 已弃用，请改用 /add 新建会话，或用 /endsession 结束当前会话并生成摘要。")
                continue
            if command_info["kind"] == "session_missing_target":
                print("用法：/session list、/session new 或 /session <session_id>")
                continue
            if command_info["kind"] == "remove_session_missing_target":
                print("用法：/rmsession <session_id>")
                continue
            if command_info["kind"] == "skill_missing_target":
                print("用法：/skill add、/skill list 或 /skill <skillname> [args]")
                continue
            if command_info["kind"] == "session_list":
                sessions = runtime.list_sessions()
                if not sessions:
                    print("暂无可用会话。")
                    continue
                for item in sessions:
                    current_mark = " *" if item.get("is_current") else ""
                    print(f"[{item['session_id']}] {item['title']} / {item['start_time']}{current_mark}")
                continue
            if command_info["kind"] == "session_add":
                session = runtime.create_new_session()
                print(f"已新建会话：{session.get('session_id', '')}")
                print(f"开始时间：{session.get('start_time', '')}")
                continue
            if command_info["kind"] == "session_switch":
                try:
                    session = runtime.switch_session(command_info["session_id"])
                except ValueError as exc:
                    print(str(exc))
                    continue
                print(f"已切换到会话：{session.get('session_id', '')}")
                print(f"会话标题：{session.get('title', '')}")
                print_session_history(runtime)
                continue
            if command_info["kind"] == "remove_session":
                try:
                    result = runtime.remove_session(command_info["session_id"])
                except ValueError as exc:
                    print(str(exc))
                    continue
                print(f"已删除会话：{result['removed_session_id']}")
                if result.get("switched"):
                    print(f"当前会话已切换为：{result.get('current_session_id', '')}")
                    if result.get("created_new"):
                        print("由于没有剩余会话，已自动新建一个空白会话。")
                continue
            if command_info["kind"] == "exec_missing_task":
                print("用法：/exec <任务内容>")
                continue
            if command_info["kind"] == "skill_list":
                skills = runtime.list_skills()
                if not skills:
                    print("当前 SKILLS 目录下暂无可用 skill。")
                    continue
                for item in skills:
                    print(f"[{item['folder']}] {item['description'] or '无描述'}")
                continue
            if command_info["kind"] == "skill_add":
                def skill_callback(event: dict):
                    event_type = event.get("type")
                    if event_type == "skill_phase":
                        print(f"[skill] {event.get('message', '')}")
                    elif event_type == "skill_result":
                        print(f"[skill] 已生成：{event.get('skill_name', '')}")

                try:
                    result = runtime.learn_skill_from_current_session(callback=skill_callback)
                except ValueError as exc:
                    print(str(exc))
                    continue
                print(result.get("chat_report", ""))
                continue
            if command_info["kind"] == "skill_run":
                def skill_exec_callback(event: dict):
                    event_type = event.get("type")
                    if event_type == "skill_phase":
                        print(f"[skill] {event.get('message', '')}")
                    elif event_type == "skill_result":
                        print(f"[skill] 执行完成：{event.get('skill_name', '')}")

                try:
                    result = runtime.execute_skill(
                        command_info["skill_name"],
                        args_text=command_info.get("skill_args", ""),
                        callback=skill_exec_callback,
                    )
                except ValueError as exc:
                    print(str(exc))
                    continue
                print(result.get("reply", ""))
                continue
            if command_info["kind"] == "end_session":
                archive_data = runtime.end_session(auto_new_session=False)
                print("当前会话已结束。")
                print(f"会话时间：{archive_data['time']}")
                print(f"会话摘要：{archive_data['msg']}")
                continue
            if command_info["kind"] == "remove_records":
                removed_count, _ = runtime.remove_records(auto_new_session=True)
                info = runtime.get_runtime_info()
                print("当前用户记录已清空。")
                print(f"已删除当前用户的 {removed_count} 个会话记录文件。")
                print(f"已自动新建会话。开始时间：{info['start_time']}")
                continue
            if command_info["kind"] == "exec":

                def exec_callback(event: dict):
                    event_type = event.get("type")
                    if event_type in {"exec_phase", "exec_plan", "exec_verify"}:
                        print(f"[exec] {event.get('message', '')}")
                    elif event_type == "skill_phase":
                        print(f"[skill] {event.get('message', '')}")
                    elif event_type == "skill_result":
                        print(f"[skill] 执行完成：{event.get('skill_name', '')}")
                    elif event_type == "exec_report":
                        print(f"[exec] 已生成执行报告：{event.get('report_path', '')}")
                    elif event_type == "exec_step_start":
                        print(f"[exec] {event.get('message', '')}")
                    elif event_type == "exec_step_done":
                        step_result = event.get("step_result", {})
                        print(
                            f"[exec] {event.get('message', '')}\n"
                            f"stdout:\n{step_result.get('stdout', '')}\n"
                            f"stderr:\n{step_result.get('stderr', '')}"
                        )

                result = runtime.execute_exec_workflow(command_info["task"], callback=exec_callback)
                report = result.get("chat_report", "")
                if report:
                    print(f"AI：{report}")
                continue
            if command_info["kind"] == "known_command":
                print(f"已匹配指令：{user_input}，但暂未实现对应程序逻辑。")
                continue

            main_cfg = runtime.config.llm["main_llm"]
            use_stream = bool(main_cfg.get("stream", False))
            show_reasoning = bool(main_cfg.get("show_reasoning", False))
            reasoning_dim = bool(main_cfg.get("reasoning_dim", True))

            if use_stream:
                stream_state = {"reasoning_started": False, "answer_started": False}

                def handle_reasoning(reasoning_text: str):
                    if not show_reasoning:
                        return
                    if not stream_state["reasoning_started"]:
                        print("思考：")
                        stream_state["reasoning_started"] = True
                    print(style_reasoning_text(reasoning_text, reasoning_dim), end="", flush=True)

                def handle_answer(answer_text: str):
                    if stream_state["reasoning_started"] and not stream_state["answer_started"]:
                        print()
                    if not stream_state["answer_started"]:
                        print("AI：", end="", flush=True)
                        stream_state["answer_started"] = True
                    print(answer_text, end="", flush=True)

                def handle_exec(event: dict):
                    event_type = event.get("type")
                    if event_type in {"exec_phase", "exec_plan", "exec_verify", "exec_step_start"}:
                        print(f"[exec] {event.get('message', '')}")
                    elif event_type == "skill_phase":
                        print(f"[skill] {event.get('message', '')}")
                    elif event_type == "skill_result":
                        print(f"[skill] 执行完成：{event.get('skill_name', '')}")
                    elif event_type == "exec_report":
                        print(f"[exec] 已生成执行报告：{event.get('report_path', '')}")
                    elif event_type == "exec_step_done":
                        step_result = event.get("step_result", {})
                        print(
                            f"[exec] {event.get('message', '')}\n"
                            f"stdout:\n{step_result.get('stdout', '')}\n"
                            f"stderr:\n{step_result.get('stderr', '')}"
                        )

                runtime.chat(
                    user_input,
                    on_answer_token=handle_answer,
                    on_reasoning_token=handle_reasoning,
                    exec_callback=handle_exec,
                )
                print()
            else:
                def handle_exec(event: dict):
                    event_type = event.get("type")
                    if event_type in {"exec_phase", "exec_plan", "exec_verify", "exec_step_start"}:
                        print(f"[exec] {event.get('message', '')}")
                    elif event_type == "skill_phase":
                        print(f"[skill] {event.get('message', '')}")
                    elif event_type == "skill_result":
                        print(f"[skill] 执行完成：{event.get('skill_name', '')}")
                    elif event_type == "exec_report":
                        print(f"[exec] 已生成执行报告：{event.get('report_path', '')}")
                    elif event_type == "exec_step_done":
                        step_result = event.get("step_result", {})
                        print(
                            f"[exec] {event.get('message', '')}\n"
                            f"stdout:\n{step_result.get('stdout', '')}\n"
                            f"stderr:\n{step_result.get('stderr', '')}"
                        )

                reply = runtime.chat(
                    user_input,
                    exec_callback=handle_exec,
                )
                print(f"AI：{reply}")
    except (KeyboardInterrupt, EOFError):
        # 非正常结束时不归档，只保存活动会话，供下次继续。
        runtime.save_current_session()
        print("\n检测到中断，当前会话已保留，可下次恢复。")
