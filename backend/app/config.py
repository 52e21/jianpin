import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ---- 成本控制相关配置 ----
# 缓存 TTL：相同任务在窗口内直接返回，不重复执行
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "600"))
# Agent LLM 循环最大轮数（拆解→工具→汇总），防止无限循环消耗 token
MAX_LLM_ROUNDS = int(os.getenv("MAX_LLM_ROUNDS", "3"))
# 单任务最多工具调用次数，超过即终止
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", "2"))
# Function Calling 采样温度，越低越稳定省 token
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
