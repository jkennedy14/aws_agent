sql_ec2_connection_pool = None

FUNCTION_CALLING_PROMPT_VERSION = 1.0
REFLECTION_PROMPT_VERSION = 1.0

DEFAULT_RAM = 8.0
DEFAULT_CPU = 2

RAVEN_API_URL = "http://nexusraven.nexusflow.ai"

RAVEN_LLM_PARAMETERS = {
    "temperature": 0.001,
    "stop": ["<bot_end>"],
    "do_sample": False,
    "max_new_tokens": 2048,
    "return_full_text": False,
}
