import json
import re
import time
from typing import Any, Dict

import boto3

from src.config import AWS_BEDROCK_MODEL_ID, AWS_REGION


def _generate_with_bedrock(prompt: str, max_tokens: int = 1200) -> str:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    last_error = ""
    for attempt in range(3):
        try:
            response = client.converse(
                modelId=AWS_BEDROCK_MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"temperature": 0.2, "maxTokens": max(256, min(max_tokens, 8000))},
            )
            contents = (
                response.get("output", {})
                .get("message", {})
                .get("content", [])
            )
            texts = [x.get("text", "") for x in contents if isinstance(x, dict)]
            return "\n".join([t for t in texts if t]).strip()
        except Exception as e:
            last_error = str(e)
            if "ThrottlingException" in last_error or "ServiceUnavailable" in last_error or "503" in last_error:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    raise RuntimeError(last_error or "Bedrock generate failed")


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def call_gemini_json(prompt: str, max_tokens: int = 1200) -> Dict[str, Any]:
    try:
        text = _generate_with_bedrock(prompt, max_tokens=max_tokens)
        parsed = _extract_json(text)
        if not parsed:
            return {"_error": "json_parse_failed"}
        return parsed
    except Exception as e:
        return {"_error": str(e)}


def call_gemini_text(prompt: str, max_tokens: int = 1200) -> str:
    try:
        return _generate_with_bedrock(prompt, max_tokens=max_tokens).strip()
    except Exception as e:
        msg = str(e)
        if "AccessDeniedException" in msg or "UnrecognizedClientException" in msg:
            return "AWS 인증 실패로 기본 템플릿 계획을 제공합니다. aws configure를 확인해주세요."
        if "429" in msg or "ThrottlingException" in msg or "quota" in msg.lower():
            return "AWS Bedrock 호출 한도 초과로 기본 템플릿 계획을 제공합니다."
        if "503" in msg or "ServiceUnavailable" in msg:
            return "AWS Bedrock 서버 혼잡(503)으로 기본 템플릿 계획을 제공합니다. 잠시 후 다시 시도해주세요."
        if "404" in msg or "NOT_FOUND" in msg:
            return "AWS Bedrock 모델 접근 오류(404)로 기본 템플릿 계획을 제공합니다."
        return "AWS Bedrock 호출 실패로 기본 템플릿 계획을 제공합니다."
