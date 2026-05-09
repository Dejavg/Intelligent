from __future__ import annotations

import json
import base64
import mimetypes
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import Assignment
from ..prompts import COMPOSITION_GRADING_PROMPT, MATH_GRADING_PROMPT
from ..settings import settings


@dataclass
class LLMResult:
    data: dict[str, Any]
    raw_text: str
    provider: str
    model: str


class LLMClient:
    """OpenAI-compatible chat-completions client.

    Works with providers that expose `/chat/completions`, including Kimi,
    DeepSeek, and other compatible gateways. API keys are read only from env.
    """

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.base_url = _resolve_base_url(settings.llm_provider, settings.llm_base_url)
        self.model = settings.llm_model or _default_model(settings.llm_provider)
        self.vision_model = settings.llm_vision_model or self.model or _default_vision_model(settings.llm_provider)
        self.api_key = settings.llm_api_key or _provider_key(settings.llm_provider)
        self.timeout = settings.llm_timeout

    @property
    def available(self) -> bool:
        return bool(settings.llm_enabled and self.base_url and self.model and self.api_key)

    @property
    def vision_available(self) -> bool:
        return bool(settings.llm_enabled and settings.llm_vision_enabled and self.base_url and self.vision_model and self.api_key)

    def grade(self, subject: str, question_type: str, ocr_text: str, assignment: Assignment) -> LLMResult:
        if not self.available:
            raise RuntimeError("LLM is not configured")

        system_prompt = MATH_GRADING_PROMPT if subject == "数学" else COMPOSITION_GRADING_PROMPT
        user_prompt = {
            "subject": subject,
            "question_type": question_type,
            "question": assignment.question,
            "standard_answer": assignment.standard_answer,
            "full_score": assignment.full_score,
            "knowledge_points": assignment.knowledge_points or [],
            "student_answer": ocr_text,
            "output_rule": "只输出一个合法 JSON 对象，不要输出 Markdown 代码块。",
        }
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        }
        data = self._post_chat_completions(payload)
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=self.model,
        )

    def extract_homework_text(self, image_path: Path, subject: str, question_type: str, assignment: Assignment) -> LLMResult:
        if not self.vision_available:
            raise RuntimeError("vision LLM is not configured")
        prompt = {
            "task": "请从这张学生作业/试卷图片中识别真实作答内容。不要使用样例答案，不要凭空补全。",
            "subject": subject,
            "question_type": question_type,
            "known_question": assignment.question,
            "output_schema": {
                "ocr_text": "完整识别文本，保留题号、公式、步骤和作文内容",
                "student_answer": "学生作答内容",
                "detected_question": "图片中识别到的题目，如无法识别可为空",
                "confidence": "0 到 1 的数字",
                "warnings": ["识别不确定或图片质量问题"],
            },
        }
        payload = {
            "model": _resolve_vision_model(self.provider, self.vision_model),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是面向教学场景的 OCR 引擎，擅长识别中文、英文、数字、数学公式和手写步骤。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                        {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
            ],
        }
        data = self._post_chat_completions(payload)
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=_resolve_vision_model(self.provider, self.vision_model),
        )

    def grade_image(
        self,
        image_path: Path,
        subject: str,
        question_type: str,
        ocr_text: str,
        assignment: Assignment,
    ) -> LLMResult:
        if not self.vision_available:
            raise RuntimeError("vision LLM is not configured")
        system_prompt = MATH_GRADING_PROMPT if subject == "数学" else COMPOSITION_GRADING_PROMPT
        user_prompt = {
            "task": "请直接根据图片中的真实学生作答进行批改。OCR 文本仅供参考；如果 OCR 与图片冲突，以图片为准。不能把标准答案当学生答案。",
            "subject": subject,
            "question_type": question_type,
            "question": assignment.question,
            "standard_answer": assignment.standard_answer,
            "full_score": assignment.full_score,
            "knowledge_points": assignment.knowledge_points or [],
            "ocr_text": ocr_text,
            "output_rule": "只输出合法 JSON 对象；必须给出非模板化评语、错因、薄弱点和学习建议。",
        }
        payload = {
            "model": _resolve_vision_model(self.provider, self.vision_model),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                        {"type": "text", "text": json.dumps(user_prompt, ensure_ascii=False)},
                    ],
                },
            ],
        }
        data = self._post_chat_completions(payload)
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=_resolve_vision_model(self.provider, self.vision_model),
        )

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise LLMHTTPError(exc.code, body[:500]) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc


class LLMHTTPError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"LLM HTTP {status_code}: {body[:300]}")


def normalize_llm_grading(raw: dict[str, Any], rule_result: dict[str, Any], subject: str) -> dict[str, Any]:
    """Make model output match the internal grading_result schema."""

    result = dict(rule_result)
    result["score"] = _number(raw.get("score"), rule_result["score"])
    result["full_score"] = _number(raw.get("full_score"), rule_result["full_score"])
    result["is_correct"] = _bool(raw.get("is_correct"), result["score"] >= result["full_score"])
    result["knowledge_points"] = _list(raw.get("knowledge_points"), rule_result.get("knowledge_points", []))
    result["weak_points"] = _list(raw.get("weak_points"), rule_result.get("weak_points", []))
    result["comment"] = str(raw.get("comment") or rule_result.get("comment") or "")
    result["suggestion"] = str(raw.get("suggestion") or rule_result.get("suggestion") or "")

    if subject == "数学":
        result["process_analysis"] = str(raw.get("process_analysis") or rule_result.get("process_analysis") or "")
        result["mistakes"] = _list(raw.get("mistakes"), rule_result.get("mistakes", []))
        result["correct_solution"] = str(raw.get("correct_solution") or rule_result.get("correct_solution") or "")
    else:
        result["content_analysis"] = str(raw.get("content_analysis") or rule_result.get("content_analysis") or "")
        result["structure_analysis"] = str(raw.get("structure_analysis") or rule_result.get("structure_analysis") or "")
        result["language_analysis"] = str(raw.get("language_analysis") or rule_result.get("language_analysis") or "")
        result["errors"] = _list(raw.get("errors"), rule_result.get("errors", []))
        result["strengths"] = _list(raw.get("strengths"), rule_result.get("strengths", []))
        result["revised_example"] = str(raw.get("revised_example") or rule_result.get("revised_example") or "")

    result["dimension_scores"] = raw.get("dimension_scores") if isinstance(raw.get("dimension_scores"), dict) else result.get("dimension_scores", {})
    result["ai_engine"] = f"LLM:{settings.llm_provider}"
    result["ai_metadata"] = {"llm_provider": settings.llm_provider}
    return result


def _resolve_base_url(provider: str, custom: str) -> str:
    if custom:
        return custom.rstrip("/")
    if provider == "kimi":
        return "https://api.moonshot.ai/v1"
    if provider == "deepseek":
        return "https://api.deepseek.com/v1"
    return custom


def _default_model(provider: str) -> str:
    if provider == "kimi":
        return "kimi-k2.6"
    if provider == "deepseek":
        return "deepseek-chat"
    return ""


def _default_vision_model(provider: str) -> str:
    if provider == "kimi":
        return "kimi-k2.5"
    return _default_model(provider)


def _resolve_vision_model(provider: str, configured_model: str) -> str:
    # As of the current Kimi vision docs, kimi-k2.5 is the multimodal model.
    # kimi-k2.6 may return HTTP 400 for image_url payloads, so fall back to k2.5
    # when users configured it for the vision path.
    if provider == "kimi" and configured_model == "kimi-k2.6":
        return "kimi-k2.5"
    return configured_model


def _provider_key(provider: str) -> str:
    import os

    if provider == "kimi":
        return os.getenv("KIMI_API_KEY", "") or os.getenv("MOONSHOT_API_KEY", "")
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_API_KEY", "")
    return os.getenv("LLM_API_KEY", "")


def _image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "yes", "1", "正确", "是"}
    return default


def _list(value: Any, default: list) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return default
