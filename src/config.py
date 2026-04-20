import os
from dotenv import load_dotenv


load_dotenv()

try:
    import streamlit as st
except Exception:
    st = None


def _get_cfg(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return str(value)
    if st is not None:
        try:
            sec = st.secrets.get(name)  # type: ignore[attr-defined]
            if sec is not None and str(sec).strip() != "":
                return str(sec)
        except Exception:
            pass
    return default


DATA_FILE = _get_cfg("DATA_FILE", "./data/data.json")
GEMINI_API_KEY = _get_cfg("GEMINI_API_KEY", "")
LLM_PROVIDER = _get_cfg("LLM_PROVIDER", "aws").lower()
AWS_REGION = _get_cfg("AWS_REGION", "us-east-1")
AWS_BEDROCK_MODEL_ID = _get_cfg("AWS_BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
TAVILY_API_KEY = _get_cfg("TAVILY_API_KEY", "").strip()
