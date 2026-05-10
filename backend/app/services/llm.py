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
        data = self._post_chat_completions(payload, timeout=max(self.timeout, 180))
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
        data = self._post_chat_completions(payload, timeout=max(self.timeout, 180))
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
        data = self._post_chat_completions(payload, timeout=max(self.timeout, 180))
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=_resolve_vision_model(self.provider, self.vision_model),
        )

    def grade_answer_sheet(self, image_path: Path, ocr_text: str, assignment: Assignment) -> LLMResult:
        if not self.vision_available:
            raise RuntimeError("vision LLM is not configured")
        user_prompt = {
            "task": (
                "请批改这张完整未批改答题卡。图片中包含题目内容和学生作答过程，"
                "不得依赖网站题库，不得把示例题或标准答案当作学生答案。"
            ),
            "requirements": [
                "先识别每一道题的题号、学科、题型、完整题干、学生作答内容。",
                "根据题干和学生作答自行判断合理标准答案或评分要点；如果题目缺少必要信息，请在 warnings 中说明。",
                "数学题要分析解题步骤、关键公式、中间计算和最终答案，支持部分分。",
                "语文/英语等主观题要按内容、结构、语言表达、语法/错别字或拼写等维度评分。",
                "逐题输出得分、满分、是否正确、错因、正确解法或修改示例、知识点、薄弱点、个性化建议。",
                "最后汇总整张答题卡总分、总满分、整体评语、共性薄弱点和后续学习建议。",
            ],
            "ocr_text_reference": ocr_text,
            "default_full_score_policy": "若图片没有标明分值，请根据题型和难度给出合理满分，并在 warnings 中说明。",
            "output_schema": {
                "detected_subjects": ["数学", "英语"],
                "score": "整张答题卡总得分，数字",
                "full_score": "整张答题卡总满分，数字",
                "is_correct": "是否全对，布尔值",
                "summary": "整体批改分析",
                "comment": "面向学生的整体个性化评语",
                "suggestion": "整体学习建议",
                "common_weak_points": ["高频薄弱点"],
                "warnings": ["识别或评分不确定说明"],
                "questions": [
                    {
                        "question_no": "题号",
                        "subject": "学科",
                        "question_type": "题型",
                        "question_text": "完整题干",
                        "student_answer": "学生作答",
                        "score": "本题得分，数字",
                        "full_score": "本题满分，数字",
                        "is_correct": "是否正确，布尔值",
                        "process_analysis": "步骤/内容分析",
                        "mistakes": [{"step": "出错步骤或原句", "error": "错误原因"}],
                        "knowledge_points": ["知识点"],
                        "weak_points": ["薄弱点"],
                        "correct_solution": "正确解法、参考答案或修改示例",
                        "comment": "本题反馈",
                        "suggestion": "本题建议"
                    }
                ]
            },
            "output_rule": "只输出一个合法 JSON 对象，不要输出 Markdown 代码块。",
        }
        payload = {
            "model": _resolve_vision_model(self.provider, self.vision_model),
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一名严谨的多学科阅卷老师，能够从整张答题卡图片中识别题目和学生答题过程，"
                        "并按照教学评分标准逐题批改。你的输出必须是可解析 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                        {"type": "text", "text": json.dumps(user_prompt, ensure_ascii=False)},
                    ],
                },
            ],
        }
        data = self._post_chat_completions(payload, timeout=max(self.timeout, 180))
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=_resolve_vision_model(self.provider, self.vision_model),
        )

    def grade_answer_sheet_text(self, ocr_text: str, assignment: Assignment) -> LLMResult:
        if not self.available:
            raise RuntimeError("LLM is not configured")
        user_prompt = {
            "task": (
                "请根据 OCR 已识别出的完整答题卡文本进行逐题批改。文本包含题目内容和学生作答过程，"
                "不得依赖网站题库，不得把示例题或标准答案当作学生答案。"
            ),
            "answer_sheet_text": ocr_text,
            "requirements": [
                "识别每一道题的题号、学科、题型、完整题干、学生作答内容。",
                "根据题干和学生作答自行判断合理标准答案或评分要点。",
                "数学题要分析运算顺序、方程步骤、关键公式、中间计算和最终答案，支持部分分。",
                "语文/英语等主观题要按内容、结构、语言表达、语法/错别字或拼写等维度评分。",
                "逐题输出得分、满分、是否正确、错因、正确解法或修改示例、知识点、薄弱点、个性化建议。",
                "最后汇总整张答题卡总分、总满分、整体评语、共性薄弱点和后续学习建议。",
            ],
            "default_full_score_policy": "若文本没有标明分值，请根据题型和难度给出合理满分，并在 warnings 中说明。",
            "output_schema": {
                "detected_subjects": ["数学", "英语"],
                "score": "整张答题卡总得分，数字",
                "full_score": "整张答题卡总满分，数字",
                "is_correct": "是否全对，布尔值",
                "summary": "整体批改分析",
                "comment": "面向学生的整体个性化评语",
                "suggestion": "整体学习建议",
                "common_weak_points": ["高频薄弱点"],
                "warnings": ["识别或评分不确定说明"],
                "questions": [
                    {
                        "question_no": "题号",
                        "subject": "学科",
                        "question_type": "题型",
                        "question_text": "完整题干",
                        "student_answer": "学生作答",
                        "score": "本题得分，数字",
                        "full_score": "本题满分，数字",
                        "is_correct": "是否正确，布尔值",
                        "process_analysis": "步骤/内容分析",
                        "mistakes": [{"step": "出错步骤或原句", "error": "错误原因"}],
                        "knowledge_points": ["知识点"],
                        "weak_points": ["薄弱点"],
                        "correct_solution": "正确解法、参考答案或修改示例",
                        "comment": "本题反馈",
                        "suggestion": "本题建议"
                    }
                ]
            },
            "output_rule": "只输出一个合法 JSON 对象，不要输出 Markdown 代码块。",
        }
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一名严谨的多学科阅卷老师。请依据用户给出的整张答题卡 OCR 文本逐题批改，"
                        "你的输出必须是可解析 JSON。"
                    ),
                },
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        }
        data = self._post_chat_completions(payload, timeout=max(self.timeout, 180))
        content = data["choices"][0]["message"]["content"]
        return LLMResult(
            data=_extract_json(content),
            raw_text=content,
            provider=self.provider,
            model=self.model,
        )

    def _post_chat_completions(self, payload: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
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
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
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


def normalize_answer_sheet_grading(raw: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    questions = raw.get("questions") if isinstance(raw.get("questions"), list) else []
    score = _number(raw.get("score"), sum(_number(q.get("score"), 0) for q in questions if isinstance(q, dict)))
    full_score = _number(raw.get("full_score"), sum(_number(q.get("full_score"), 0) for q in questions if isinstance(q, dict)) or 100)
    mistakes: list[dict[str, Any]] = []
    knowledge_points: list[str] = []
    weak_points: list[str] = []
    dimension_scores: dict[str, float] = {}
    correct_solutions: list[str] = []

    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        question_no = str(question.get("question_no") or index)
        q_score = _number(question.get("score"), 0)
        q_full = _number(question.get("full_score"), 0)
        dimension_scores[f"第{question_no}题"] = q_score
        for mistake in _list(question.get("mistakes"), []):
            if isinstance(mistake, dict):
                mistakes.append(
                    {
                        "step": f"第{question_no}题：{mistake.get('step') or question.get('student_answer') or '作答'}",
                        "error": mistake.get("error") or mistake.get("reason") or "存在需要订正的问题。",
                    }
                )
            else:
                mistakes.append({"step": f"第{question_no}题", "error": str(mistake)})
        knowledge_points.extend(str(item) for item in _list(question.get("knowledge_points"), []) if item)
        weak_points.extend(str(item) for item in _list(question.get("weak_points"), []) if item)
        if question.get("correct_solution"):
            correct_solutions.append(f"第{question_no}题：{question.get('correct_solution')}")
        if q_full and q_score < q_full and not _list(question.get("mistakes"), []):
            mistakes.append({"step": f"第{question_no}题", "error": question.get("process_analysis") or "本题未得满分，请查看分析。"})

    common_weak = _list(raw.get("common_weak_points"), [])
    weak_points.extend(str(item) for item in common_weak if item)
    is_correct = _bool(raw.get("is_correct"), full_score > 0 and score >= full_score)

    return {
        "subject": "自动识别",
        "score": score,
        "full_score": full_score,
        "is_correct": is_correct,
        "process_analysis": str(raw.get("summary") or "已按整张答题卡逐题完成批改。"),
        "content_analysis": str(raw.get("summary") or ""),
        "structure_analysis": "",
        "language_analysis": "",
        "mistakes": mistakes,
        "errors": [],
        "strengths": _list(raw.get("strengths"), []),
        "knowledge_points": unique_list(knowledge_points),
        "weak_points": unique_list(weak_points),
        "dimension_scores": dimension_scores,
        "correct_solution": "\n".join(correct_solutions),
        "revised_example": None,
        "comment": str(raw.get("comment") or "本次答题卡已完成逐题批改，请重点查看扣分题目的错因和建议。"),
        "suggestion": str(raw.get("suggestion") or "建议先订正错题，再按薄弱知识点进行针对性练习。"),
        "ai_engine": f"LLM:{provider}:{model}",
        "ai_metadata": {
            "llm_provider": provider,
            "llm_model": model,
            "answer_sheet": {
                "detected_subjects": _list(raw.get("detected_subjects"), []),
                "score": score,
                "full_score": full_score,
                "warnings": _list(raw.get("warnings"), []),
                "questions": questions,
                "summary": raw.get("summary") or "",
            },
        },
    }


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


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
