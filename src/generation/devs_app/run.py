import sys
import os
import json
import yaml
import argparse
import inspect
import ast
import threading
from pathlib import Path
from dotenv import load_dotenv
from smolagents import LiteLLMModel, CodeAgent, ToolCallingAgent, Tool
from agent_support.agent_conversation_ui import GradioUI
from devs_display.backend.server import DEFAULT_REGISTRY_PATH, run_devs_display_backend
from agent_support.monitoring import AgentLogger, LogLevel
from datetime import datetime

import litellm

litellm.register_model(
    {
        "openai/qwen3.6-plus": {
            "litellm_provider": "openai",
            "mode": "chat",
            "max_input_tokens": 131072,
            "max_output_tokens": 131072,
            "max_tokens": 65536,
        },
        "openrouter/deepseek/deepseek-v4-flash": {
            "litellm_provider": "openrouter",
            "mode": "chat",
            "max_input_tokens": 1048576,
            "max_output_tokens": 131072,
            "max_tokens": 1048576,
        },
        "openrouter/deepseek/deepseek-v4-pro-0813": {
            "litellm_provider": "openrouter",
            "mode": "chat",
            "max_input_tokens": 1048576,
            "max_output_tokens": 384000,
            "max_tokens": 1048576,
        },
        "openrouter/qwen/qwen3-coder": {
            "litellm_provider": "openrouter",
            "mode": "chat",
            "max_input_tokens": 200000,
            "max_output_tokens": 200000,
            "max_tokens": 200000,
        },
        "openrouter/z-ai/glm-4.7": {
            "litellm_provider": "openrouter",
            "mode": "chat",
            "max_input_tokens": 200000,
            "max_output_tokens": 128000,
            "max_tokens": 200000,
        },
    }
)

from default_tools.file_editing.file_editing_tools import (
    ListDir,
    SeeTextFile,
    ModifyFile,
    SmartReplace,
    CreateFileWithContent,
)
from devs_tools.devs_construct_recon.devs_construct_dyn_fast import (
    DEVSConstructTreeFastConcur as DEVSConstructRecon,
)
from devs_tools.devs_construct_recon.wrapped_completion import (
    set_max_output_tokens as set_recon_max_output_tokens,
)
from devs_tools.devs_construct_recon.variants import get_recon_variant_profile
from devs_tools.devs_construct_recon.tools.simulation.devs_execute import DEVSExecute
import tempfile
import time

from collections import defaultdict

# Load environment variables
load_dotenv(override=True)


class TokenTracker:
    def __init__(self):
        # 结构: {model_name: {'input': 0, 'output': 0, 'thinking': 0, 'calls': 0, 'total': 0}}
        self.stats = defaultdict(
            lambda: {"input": 0, "output": 0, "thinking": 0, "calls": 0, "total": 0}
        )
        self._lock = threading.Lock()

    def track(self, kwargs, completion_response, start_time, end_time):
        """LiteLLM 成功回调函数"""
        try:
            # 1. 获取模型名称 (优先取 response 中的，如果没有则取调用参数中的)
            # 兼容对象属性访问 (response.model) 和字典访问 (response['model'])
            model_name = (
                getattr(completion_response, "model", None)
                or completion_response.get("model")
                or kwargs.get("model")
                or "unknown-model"
            )

            # 2. 获取 usage 对象
            # usage 可能是一个对象 (Pydantic) 也可能是一个字典
            if hasattr(completion_response, "usage"):
                usage = completion_response.usage
            else:
                usage = completion_response.get("usage", None)

            if not usage:
                return

            # 3. 提取标准 Token (兼容 对象.属性 和 字典.get)
            if hasattr(usage, "prompt_tokens"):
                input_tokens = getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "completion_tokens", 0)
                total_tokens = getattr(usage, "total_tokens", 0)
                # 获取 details 对象
                details = getattr(usage, "completion_tokens_details", None)
            else:
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                # 获取 details 字典
                details = usage.get("completion_tokens_details", None)

            # 4. 提取 "思考/推理" Token (修复点)
            thinking_tokens = 0
            if details:
                if isinstance(details, dict):
                    # 如果是字典，用 get
                    thinking_tokens = details.get("reasoning_tokens", 0)
                else:
                    # 如果是 Wrapper 对象，用 getattr
                    thinking_tokens = getattr(details, "reasoning_tokens", 0)

            # 5. 累加数据
            with self._lock:
                self.stats[model_name]["input"] += input_tokens
                self.stats[model_name]["output"] += output_tokens
                self.stats[model_name]["thinking"] += thinking_tokens
                self.stats[model_name]["calls"] += 1
                self.stats[model_name]["total"] += total_tokens

        except Exception as e:
            # 打印错误但不中断程序，方便排查
            print(f"[TokenTracker Error] {str(e)}")

    def get_report(self):
        """返回最终需要的 dict 格式"""
        with self._lock:
            return {model: dict(counts) for model, counts in self.stats.items()}

    def print_summary(self):
        """打印易读的统计信息"""
        print("\n" + "=" * 30)
        print("  TOKEN USAGE SUMMARY")
        print("=" * 30)
        for model, counts in self.get_report().items():
            print(f"Model: {model}")
            print(f"  - Calls:    {counts['calls']}")
            print(f"  - Input:    {counts['input']}")
            print(f"  - Output:   {counts['output']}")
            if counts["thinking"] > 0:
                print(f"  - Thinking: {counts['thinking']} (Included in Output)")
            print(f"  - Total:    {counts['total']}")
            print("-" * 30)


# --- 初始化并注册回调 ---
token_tracker = TokenTracker()
litellm.success_callback = [token_tracker.track]


def _install_output_token_cap(max_output_tokens: int | None) -> None:
    """Apply an explicit cap to every synchronous LiteLLM call in this process."""
    if max_output_tokens is None:
        set_recon_max_output_tokens(None)
        return
    if max_output_tokens < 1:
        raise ValueError("max_output_tokens must be positive")
    original_completion = litellm.completion

    def capped_completion(*args, **kwargs):
        for key in ("max_tokens", "max_completion_tokens"):
            if key in kwargs and kwargs[key] is not None:
                kwargs[key] = min(int(kwargs[key]), max_output_tokens)
                break
        else:
            kwargs["max_tokens"] = max_output_tokens
        return original_completion(*args, **kwargs)

    litellm.completion = capped_completion
    set_recon_max_output_tokens(max_output_tokens)


def create_devs_agent(
    model_id: dict,
    working_directory="working_dir",
    persistent_storage="persistent_storage",
    index_dir="index_dir",
    signature=None,
    disable_check=False,
    concur=False,
    agent_planning_interval=10,
    agent_max_steps=80,
    manager_use_strong=False,
    agent_log_level="DEBUG",
    concur_num=4,
    construct_variant="recon_consensus_repair2",
    enable_schema_repair=False,
    enable_final_repair=False,
    enable_quick_smoke_repair=False,
    root_plan_draft_count=None,
):
    ### Set up the model ###
    # here we use LiteLLMModel.
    # Alternatively, you can use InferenceClientModel, VLLMModel or TransformersModel depending on your chosen LLM model backend
    # Use a stronger manager model in checked/debug workflows for better tool orchestration.
    manager_model_id = (
        model_id["strong"]
        if (manager_use_strong or not disable_check)
        else model_id["weak"]
    )
    model = LiteLLMModel(model_id=manager_model_id)

    ### Set up the tools ###
    # tools for working with the local working directory
    working_directory_file_editing_tools = [
        ListDir(working_directory),
        SeeTextFile(working_directory),
        ModifyFile(working_directory),
        CreateFileWithContent(working_directory),
    ]

    devs_tools: list[Tool] = []

    print(f"disable_check = {disable_check}")

    construct_variants = {
        "recon": DEVSConstructRecon,
        "recon_sr": DEVSConstructRecon,
        "recon_critic": DEVSConstructRecon,
        "recon_raw": DEVSConstructRecon,
        "recon_schema_repair": DEVSConstructRecon,
        "recon_align_raw": DEVSConstructRecon,
        "recon_consensus_raw": DEVSConstructRecon,
        "recon_consensus_repair2": DEVSConstructRecon,
    }
    try:
        construct_cls = construct_variants[construct_variant]
    except KeyError as exc:
        supported = ", ".join(sorted(construct_variants))
        raise ValueError(
            f"Unsupported construct_variant '{construct_variant}'. Supported variants: {supported}"
        ) from exc

    construct_file_tools = {
        "read": SeeTextFile(working_directory),
        "write": SmartReplace(working_directory),
        "list": ListDir(working_directory),
    }
    effective_concur_num = concur_num if concur else 1
    effective_schema_repair = enable_schema_repair or construct_variant in {
        "recon_sr",
        "recon_critic",
        "recon_raw",
        "recon_schema_repair",
        "recon_align_raw",
        "recon_consensus_raw",
    }
    profile = get_recon_variant_profile(construct_variant)
    effective_root_plan_draft_count = (
        int(profile.get("root_plan_draft_count", 0))
        if root_plan_draft_count is None
        else root_plan_draft_count
    )
    print(
        f"construct_variant = {construct_variant}, "
        f"construct_cls = {construct_cls.__name__}, "
        f"concur_num = {effective_concur_num}, "
        f"enable_schema_repair = {effective_schema_repair}, "
        f"enable_final_repair = {enable_final_repair}, "
        f"enable_quick_smoke_repair = {enable_quick_smoke_repair}, "
        f"root_plan_draft_count = {effective_root_plan_draft_count}, "
        f"recon_profile = {profile or 'default'}"
    )

    construct_kwargs = {
        "file_tools": construct_file_tools,
        "model_id": model_id,
        "working_directory": working_directory,
        "disable_check": disable_check,
        "concur_num": effective_concur_num,
        "enable_schema_repair": effective_schema_repair,
        "enable_final_repair": enable_final_repair,
        "enable_quick_smoke_repair": enable_quick_smoke_repair,
        "enable_alignment_critic": profile.get("enable_alignment_critic", False),
        "root_plan_draft_count": effective_root_plan_draft_count,
        "parent_use_raw_child_code": profile.get("parent_use_raw_child_code", False),
        "summarize_after_generation": profile.get("summarize_after_generation", True),
        # Keep the code-generation context fixed across the factorial profiles.
        # The critic sees the full tree once; atomic prompts should remain local.
        "rich_alignment_context": profile.get("rich_alignment_context", False),
        "continue_with_locked_interfaces": profile.get(
            "continue_with_locked_interfaces", False
        ),
        "root_endpoint_audit_example": profile.get(
            "root_endpoint_audit_example", False
        ),
        "quick_smoke_max_repairs": profile.get("quick_smoke_max_repairs", 1),
    }
    supported_params = inspect.signature(construct_cls).parameters
    construct_kwargs = {
        key: value for key, value in construct_kwargs.items()
        if key in supported_params
    }
    devs_tree_construct_tool = construct_cls(**construct_kwargs)
    devs_tools.append(devs_tree_construct_tool)

    devs_execute_tool = DEVSExecute(working_directory=working_directory)
    devs_tools.append(devs_execute_tool)

    ### Set up the agent ###
    app_name = "devs_app"
    level_map = {
        "DEBUG": LogLevel.DEBUG,
        "INFO": LogLevel.INFO,
        "WARNING": LogLevel.INFO,
        "ERROR": LogLevel.ERROR,
    }
    resolved_level = level_map.get(str(agent_log_level).upper(), LogLevel.DEBUG)
    # Here we configure the logger to save the agent's log to a txt file in the persistent storage
    mananger_logger = AgentLogger(
        level=resolved_level,
        save_to_file=os.path.join(
            persistent_storage, f"manager_agent_log_{signature}.txt"
        ),
        name=app_name,
    )
    # tools = working_directory_file_editing_tools+search_tools+knowledge_base_retrieval_tools+knowledge_base_update_tools+visual_qa_tools+devs_tools
    tools = working_directory_file_editing_tools + devs_tools
    # manager agent is responsible for directly talking with user and call sub-agents to complete user tasks
    manager_agent = CodeAgent(
        tools=tools,
        model=model,
        managed_agents=[],
        planning_interval=agent_planning_interval,
        additional_authorized_imports=["json", "re", "math", "typing", "pathlib"],
        max_steps=agent_max_steps,
        logger=mananger_logger,
        name=app_name,
        description="This is a DEVS agent application that can construct, execute, and analyze DEVS models using xDEVS.py.",
    )
    mananger_logger.visualize_agent_tree(manager_agent)
    return manager_agent


def _normalize_tool_params(tool_params):
    if not isinstance(tool_params, dict):
        raise TypeError("Tool parameters must be a dict")

    if not tool_params.get("base_folder"):
        tool_params["base_folder"] = "."

    tool_params.setdefault("skip_simulation_check", False)
    tool_params.setdefault("only_ensure_executable", False)

    requirements = tool_params.get("requirements")
    if isinstance(requirements, dict):
        sections = []
        for key in ("general", "scenario", "args_input_output"):
            value = requirements.get(key)
            if value:
                sections.append(f"{key}:\n{value}")
        tool_params["requirements"] = "\n\n".join(sections) if sections else str(requirements)
    elif requirements is not None and not isinstance(requirements, str):
        tool_params["requirements"] = str(requirements)

    return tool_params


def _entry_fingerprint(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _validate_direct_generation_contract(
    result,
    expected_entry_path: Path,
    entry_before: tuple[int, int] | None,
) -> str | None:
    """Return an error string when the direct generation contract is unmet."""
    result_text = str(result)
    if not result_text.lstrip().startswith("Build Success!"):
        return f"Generator did not report Build Success: {result_text[:200]}"
    return _validate_entry_artifact(expected_entry_path, entry_before)


def _validate_entry_artifact(
    expected_entry_path: Path,
    entry_before: tuple[int, int] | None,
) -> str | None:
    """Require a fresh, non-empty, syntactically valid Python entry point."""
    entry_after = _entry_fingerprint(expected_entry_path)
    if entry_after is None or entry_after[1] == 0:
        return f"Entry file is missing or empty: {expected_entry_path}"
    if entry_before is not None and entry_after == entry_before:
        return f"Entry file was not freshly generated: {expected_entry_path}"
    try:
        ast.parse(expected_entry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return f"Entry file is not valid Python: {exc}"
    return None


def _find_existing_display_workspace(base_temp_dir: str) -> str | None:
    registry_path = Path(DEFAULT_REGISTRY_PATH)
    if registry_path.exists():
        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            sessions = [
                entry for entry in registry.get("sessions", [])
                if entry.get("workspace_path") and Path(entry["workspace_path"]).is_dir()
            ]
            sessions.sort(key=lambda entry: entry.get("updated_at") or entry.get("last_seen_at") or entry.get("created_at") or "", reverse=True)
            if sessions:
                return sessions[0]["workspace_path"]
        except Exception as exc:
            print(f"[devs_display] Failed to read session registry: {exc}")
    return None


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="Run the DEVS Agent")
    argparser.add_argument(
        "--model_id",
        type=str,
        default="gpt-4.1",
        help="The ID of the model to use for the agent.",
    )
    argparser.add_argument(
        "--model_id_strong",
        type=str,
        default="gpt-5.2",
        help="The ID of the model to use for the agent.",
    )
    argparser.add_argument(
        "--max_output_tokens",
        type=int,
        default=None,
        help="Optional per-call output-token cap applied to all synchronous LiteLLM calls.",
    )
    argparser.add_argument(
        "--mode",
        type=str,
        default="gradio",
        choices=["gradio", "cli", "server", "tool_debug", "tool_debug_agent"],
        help="The mode to run the agent in. 'gradio' for web interface, 'cli' for command line interface.",
    )
    argparser.add_argument(
        "--working_directory",
        type=str,
        default=None,
        help="The directory where the agent will store its working files.",
    )
    argparser.add_argument(
        "--persistent_storage",
        type=str,
        default=None,
        help="A structured directory that contains the persistent files, e.g. code snippets, papers, and other resources.",
    )
    argparser.add_argument(
        "--index_dir",
        type=str,
        default=None,
        help="The directory where the vector store index will be stored.",
    )
    argparser.add_argument(
        "--debug_args_file",
        type=str,
        default="devs_app/devs_model_inputs/example1.json",
        help="Path to the JSON file containing tool parameters for debugging.",
    )
    argparser.add_argument(
        "--target_tool",
        type=str,
        default="devs_construct_tree",
        help="The name of the tool you want to debug (must match tool.name).",
    )
    argparser.add_argument(
        "--disable_check",
        action="store_true",
        help="Disable the check",
    )
    argparser.add_argument(
        "--concur_generate",
        action="store_true",
    )
    argparser.add_argument(
        "--agent_planning_interval",
        type=int,
        default=10,
        help="Planning interval for manager CodeAgent.",
    )
    argparser.add_argument(
        "--agent_max_steps",
        type=int,
        default=80,
        help="Max reasoning steps for manager CodeAgent.",
    )
    argparser.add_argument(
        "--manager_use_strong",
        action="store_true",
        help="Force manager CodeAgent to use strong model for orchestration.",
    )
    argparser.add_argument(
        "--agent_log_level",
        type=str,
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity for manager agent runtime.",
    )
    argparser.add_argument(
        "--concur_num",
        type=int,
        default=4,
        help="Concurrency used by devs_construct_tree concurrent mode.",
    )
    argparser.add_argument(
        "--construct_variant",
        type=str,
        default="recon_consensus_repair2",
        choices=["recon", "recon_sr", "recon_critic", "recon_raw", "recon_schema_repair", "recon_align_raw", "recon_consensus_raw", "recon_consensus_repair2"],
        help="Select constructor implementation variant.",
    )
    argparser.add_argument(
        "--enable_schema_repair",
        action="store_true",
        help="Repair structured-output parse/schema failures with an extra same-model API call.",
    )
    argparser.add_argument(
        "--enable_final_repair",
        action="store_true",
        help="Run the expensive final runtime repair coding agent after packaging.",
    )
    argparser.add_argument(
        "--enable_quick_smoke_repair",
        action="store_true",
        help=(
            "Run one bounded default invocation and, only for a traceback localized "
            "to one generated model, try one transactional regeneration."
        ),
    )
    argparser.add_argument(
        "--root_plan_draft_count",
        type=int,
        default=None,
        help=(
            "Root plan candidates before the final rewrite: 0 keeps one-shot "
            "planning, 1 enables draft+final, and 2+ enables parallel drafts+final."
        ),
    )
    args = argparser.parse_args()
    _install_output_token_cap(args.max_output_tokens)

    # Ensure the base temp_files directory exists
    base_temp_dir = "devs_app/working_dirs"
    Path(base_temp_dir).mkdir(parents=True, exist_ok=True)

    # Server mode owns workspace/session registry selection. If the caller does
    # not pass a workspace, reuse the latest registered session workspace.
    if args.working_directory is None:
        existing_workspace = _find_existing_display_workspace(base_temp_dir) if args.mode == "server" else None
        if existing_workspace:
            args.working_directory = existing_workspace
            print(f"[devs_display] Reusing existing workspace: {args.working_directory}")
        else:
            curr_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            args.working_directory = tempfile.mkdtemp(
                dir=base_temp_dir, prefix=f"working_directory_{curr_time}_"
            )
    if args.persistent_storage is None:
        args.persistent_storage = "devs_app/persistent_storage"
    Path(args.persistent_storage).mkdir(parents=True, exist_ok=True)
    if args.index_dir is None:
        args.index_dir = "devs_app/index_dir"
    Path(args.index_dir).mkdir(parents=True, exist_ok=True)

    # create a date time signature
    date_time_signature = time.strftime("%Y%m%d_%H%M%S")

    # Create the agent
    manager_agent = create_devs_agent(
        model_id={
            "weak": args.model_id,
            "strong": args.model_id_strong,
        },
        working_directory=args.working_directory,
        persistent_storage=args.persistent_storage,
        index_dir=args.index_dir,
        signature=date_time_signature,
        disable_check=args.disable_check,
        concur=args.concur_generate,
        agent_planning_interval=args.agent_planning_interval,
        agent_max_steps=args.agent_max_steps,
        manager_use_strong=args.manager_use_strong,
        agent_log_level=args.agent_log_level,
        concur_num=args.concur_num,
        construct_variant=args.construct_variant,
        enable_schema_repair=args.enable_schema_repair,
        enable_final_repair=args.enable_final_repair,
        enable_quick_smoke_repair=args.enable_quick_smoke_repair,
        root_plan_draft_count=args.root_plan_draft_count,
    )

    if args.mode == "cli":
        # Run the agent in CLI mode
        while True:
            try:
                manager_agent.run(
                    "Based on the conversation so far, talk with the user to understand the user's task and complete the task.",
                    reset=False,
                )
                print("Agent finished running. Waiting for next command...")
                print("Press Ctrl+C to exit.")
            except KeyboardInterrupt:
                print("Exiting...")
                break

    elif args.mode == "gradio":
        # Run the agent in Gradio mode
        print("Launching Gradio UI...")
        GradioUI(agent=manager_agent, file_upload_folder=args.working_directory).launch(
            share=False
        )

    elif args.mode == "server":
        print("Launching API Server...")
        def devs_display_agent_factory(workspace: str):
            workspace_signature = f"{date_time_signature}_{Path(workspace).name}"
            return create_devs_agent(
                model_id={
                    "weak": args.model_id,
                    "strong": args.model_id_strong,
                },
                working_directory=workspace,
                persistent_storage=args.persistent_storage,
                index_dir=args.index_dir,
                signature=workspace_signature,
                disable_check=args.disable_check,
                concur=args.concur_generate,
                agent_planning_interval=args.agent_planning_interval,
                agent_max_steps=args.agent_max_steps,
                manager_use_strong=args.manager_use_strong,
                agent_log_level=args.agent_log_level,
                concur_num=args.concur_num,
                construct_variant=args.construct_variant,
                enable_schema_repair=args.enable_schema_repair,
                enable_final_repair=args.enable_final_repair,
                root_plan_draft_count=args.root_plan_draft_count,
            )

        run_devs_display_backend(
            manager_agent=manager_agent,
            working_directory=args.working_directory,
            agent_factory=devs_display_agent_factory,
        )

    elif args.mode == "tool_debug":
        # === 适配器模式：将内部 Tool 包装为标准 Code Agent 行为 ===
        print(f"--- [Adapter] Starting Tool: {args.target_tool} ---")

        # 1. 准备参数
        param_file = Path(args.debug_args_file)
        if not param_file.exists():
            print(f"Error: Parameter file '{args.debug_args_file}' not found.")
            sys.exit(1)

        try:
            with open(param_file, "r", encoding="utf-8") as f:
                if param_file.suffix.lower() == ".json":
                    tool_params = json.load(f)
                elif param_file.suffix.lower() in [".yaml", ".yml"]:
                    tool_params = yaml.safe_load(f)
                else:
                    raise Exception(f"Unsupported file format: {param_file}")
        except Exception as e:
            print(f"Error: Failed to parse parameters: {e}")
            sys.exit(1)

        # 2. 确定“契约”路径
        # 评测器通过 CLI 传入 working_directory (沙盒根目录)
        # YAML 参数传入 base_folder (项目子目录)
        tool_params = _normalize_tool_params(tool_params)
        sandbox_root = Path(args.working_directory).resolve()
        base_folder_name = tool_params.get("base_folder", ".")  # 默认为当前目录

        # 计算出仿真模型实际应该存在的目录 (Simulation CWD)
        # e.g., /tmp/work_dir_123/abp_model
        sim_cwd = sandbox_root / base_folder_name

        # 约定的入口文件名
        entry_filename = "run.py"
        expected_entry_path = sim_cwd / entry_filename
        entry_before = _entry_fingerprint(expected_entry_path)

        print(f"[Adapter] Sandbox Root: {sandbox_root}")
        print(f"[Adapter] Expected Project Root: {sim_cwd}")
        print(f"[Adapter] Expected Entry Point: {expected_entry_path}")

        # 3. 查找并执行工具
        target_tool = next(
            (
                tool
                for name, tool in manager_agent.tools.items()
                if name == args.target_tool
            ),
            None,
        )
        if not target_tool:
            print(f"Error: Tool '{args.target_tool}' not found.")
            sys.exit(1)

        try:
            start_time = time.time()
            # === 核心：调用工具生成代码 ===
            # 工具内部会使用 args.working_directory 作为基础，并创建 base_folder
            result = target_tool.forward(**tool_params)
            end_time = time.time()

            print(f"\n--- Tool Execution Finished ({end_time - start_time:.2f}s) ---")

            usage_report = token_tracker.get_report()
            # 也可以在这里直接打印到控制台看一眼
            token_tracker.print_summary()

            # 4. 验证契约 (Verify Contract)
            output_info = {
                "status": "fail",
                "sim_cwd": str(sim_cwd),
                "sim_entry": entry_filename,
                "timestamp": datetime.now().isoformat(),
                "token_usage": usage_report,
            }

            contract_error = _validate_direct_generation_contract(
                result, expected_entry_path, entry_before
            )
            if not sim_cwd.exists():
                output_info["error"] = (
                    f"Base folder '{base_folder_name}' was not created."
                )
            elif contract_error:
                output_info["error"] = contract_error
            else:
                output_info["status"] = "success"
                # 还可以把工具返回的文本摘要放进去
                output_info["tool_response_preview"] = str(result)[:100]

            # 5. 输出标准握手信号 (Handshake Signal)
            # 无论成功失败，都输出这段 JSON，供 Pipeline 解析
            print("\n<<<GENERATION_RESULT>>>")
            print(json.dumps(output_info, indent=None))
            print("<<<GENERATION_RESULT>>>")

            if output_info["status"] != "success":
                # 如果生成失败，Adapter 本身以非0退出，方便 Shell 脚本捕获
                sys.exit(1)

        except Exception as e:
            print("\n=== Execution Crashed ===")
            import traceback

            traceback.print_exc()

            error_info = {"status": "crash", "error": str(e)}
            print("\n<<<GENERATION_RESULT>>>")
            print(json.dumps(error_info))
            print("<<<GENERATION_RESULT>>>")
            sys.exit(1)

    elif args.mode == "tool_debug_agent":
        print(f"--- [Integrated Debug Agent] Starting Tool: {args.target_tool} ---")

        param_file = Path(args.debug_args_file)
        if not param_file.exists():
            print(f"Error: Parameter file '{args.debug_args_file}' not found.")
            sys.exit(1)

        try:
            with open(param_file, "r", encoding="utf-8") as f:
                if param_file.suffix.lower() == ".json":
                    tool_params = json.load(f)
                elif param_file.suffix.lower() in [".yaml", ".yml"]:
                    tool_params = yaml.safe_load(f)
                else:
                    raise Exception(f"Unsupported file format: {param_file}")
        except Exception as e:
            print(f"Error: Failed to parse parameters: {e}")
            sys.exit(1)

        tool_params = _normalize_tool_params(tool_params)
        sandbox_root = Path(args.working_directory).resolve()
        base_folder_name = str(tool_params.get("base_folder", "."))
        sim_cwd = sandbox_root / base_folder_name
        entry_filename = "run.py"
        expected_entry_path = sim_cwd / entry_filename
        entry_before = _entry_fingerprint(expected_entry_path)
        smoke_stdout = f"{base_folder_name}/_debug/smoke.stdout"
        smoke_stderr = f"{base_folder_name}/_debug/smoke.stderr"

        debug_param_file = (
            sandbox_root / base_folder_name / "_debug" / "integrated_tool_params.json"
        )
        debug_param_file.parent.mkdir(parents=True, exist_ok=True)
        debug_param_file.write_text(
            json.dumps(tool_params, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        compact_prompt = (
            "Run an integrated generation-debug loop with tools only.\n"
            f"Step 1: read params from file '{base_folder_name}/_debug/integrated_tool_params.json', then call `{args.target_tool}` exactly once using those params.\n"
            "Step 2: smoke test with `devs_execute` using:\n"
            f"- project_path='{base_folder_name}'\n"
            "- main_file='run.py'\n"
            "- timeout=120\n"
            "- command_args='--simulate_time 3 --seed 0'\n"
            f"- stdout_file='{smoke_stdout}'\n"
            f"- stderr_file='{smoke_stderr}'\n"
            "Step 3: if smoke test fails, do minimal targeted fixes and rerun smoke test (max 2 repair loops).\n"
            "Step 4: finish with a short summary including final paths."
        )

        try:
            start_time = time.time()
            result = manager_agent.run(compact_prompt, reset=True)
            end_time = time.time()
            print(f"\n--- Integrated Agent Finished ({end_time - start_time:.2f}s) ---")

            usage_report = token_tracker.get_report()
            token_tracker.print_summary()

            output_info = {
                "status": "fail",
                "sim_cwd": str(sim_cwd),
                "sim_entry": entry_filename,
                "timestamp": datetime.now().isoformat(),
                "token_usage": usage_report,
                "smoke_stdout": str(sandbox_root / smoke_stdout),
                "smoke_stderr": str(sandbox_root / smoke_stderr),
            }

            contract_error = _validate_entry_artifact(
                expected_entry_path, entry_before
            )
            if not sim_cwd.exists():
                output_info["error"] = (
                    f"Base folder '{base_folder_name}' was not created."
                )
            elif contract_error:
                output_info["error"] = contract_error
            else:
                output_info["status"] = "success"
                output_info["tool_response_preview"] = str(result)[:200]

            print("\n<<<GENERATION_RESULT>>>")
            print(json.dumps(output_info, indent=None))
            print("<<<GENERATION_RESULT>>>")

            if output_info["status"] != "success":
                sys.exit(1)

        except Exception as e:
            print("\n=== Integrated Execution Crashed ===")
            import traceback

            traceback.print_exc()
            error_info = {"status": "crash", "error": str(e)}
            print("\n<<<GENERATION_RESULT>>>")
            print(json.dumps(error_info))
            print("<<<GENERATION_RESULT>>>")
            sys.exit(1)
