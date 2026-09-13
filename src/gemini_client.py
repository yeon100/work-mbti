import json
import re
import time
from typing import Any, Dict, Optional

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


def _generate_with_bedrock_image(
    prompt: str,
    image_bytes: bytes,
    image_format: str,
    max_tokens: int = 1200,
) -> str:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    last_error = ""
    fmt = (image_format or "png").lower().replace("jpeg", "jpg")
    for attempt in range(3):
        try:
            response = client.converse(
                modelId=AWS_BEDROCK_MODEL_ID,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": fmt,
                                    "source": {"bytes": image_bytes},
                                }
                            },
                            {"text": prompt},
                        ],
                    }
                ],
                inferenceConfig={"temperature": 0.1, "maxTokens": max(256, min(max_tokens, 8000))},
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
    raise RuntimeError(last_error or "Bedrock image generate failed")


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    # ```json ... ``` 블록 우선 파싱
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            pass

    # 전체 텍스트에서 가장 바깥 JSON 객체 구간을 브레이스 매칭으로 추출
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break

    # 마지막 보정: 줄바꿈/설명 텍스트가 섞였을 때 첫 객체 재시도
    match = re.search(r"\{[\s\S]*?\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}
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


def call_gemini_image_json(
    prompt: str,
    image_bytes: bytes,
    image_format: Optional[str] = None,
    max_tokens: int = 1200,
) -> Dict[str, Any]:
    try:
        text = _generate_with_bedrock_image(
            prompt,
            image_bytes=image_bytes,
            image_format=(image_format or "png"),
            max_tokens=max_tokens,
        )
        parsed = _extract_json(text)
        if not parsed:
            return {"_error": "json_parse_failed"}
        return parsed
    except Exception as e:
        return {"_error": str(e)}
