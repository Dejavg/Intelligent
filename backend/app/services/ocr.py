from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..database import UPLOAD_DIR
from ..models import Assignment, Submission
from ..settings import settings
from .llm import LLMClient, LLMHTTPError


@dataclass
class OCRResult:
    raw_text: str
    confidence: float
    blocks: list[dict]
    engine: str = "MockOCR"
    formula_latex: str | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "blocks": self.blocks,
            "engine": self.engine,
            "formula_latex": self.formula_latex,
            "warnings": self.warnings or [],
        }


class OCRService:
    """OCR adapter with mock, PaddleOCR, Baidu OCR, and Tencent OCR slots."""

    def recognize(self, submission: Submission, assignment: Assignment) -> OCRResult:
        warnings: list[str] = []
        try:
            if settings.ocr_provider in {"llm", "vision", "kimi"}:
                result = self._recognize_with_llm_vision(submission, assignment)
            elif settings.llm_enabled and settings.llm_vision_ocr and submission.image_url:
                result = self._recognize_with_llm_vision(submission, assignment)
            elif settings.ocr_provider == "paddle":
                result = self._recognize_with_paddle(submission)
            elif settings.ocr_provider == "baidu":
                result = self._recognize_with_baidu(submission)
            elif settings.ocr_provider == "tencent":
                result = self._recognize_with_tencent(submission)
            elif submission.image_url and not settings.allow_mock_for_uploaded_images:
                result = OCRResult(
                    raw_text="",
                    confidence=0,
                    blocks=[],
                    engine="NoOCRConfigured",
                    warnings=[
                        "检测到真实上传图片，但当前未配置真实 OCR 或视觉大模型；已停止使用模拟样例，避免误判为满分。"
                    ],
                )
            else:
                result = self._mock_recognize(submission, assignment)
        except Exception as exc:
            if not settings.ocr_fallback_to_mock:
                return self._unavailable_result(submission, exc)
            warnings.append(f"{settings.ocr_provider} OCR fallback: {exc}")
            result = self._mock_recognize(submission, assignment)

        if submission.subject == "数学" and result.engine != "NoOCRConfigured":
            try:
                formula_latex = FormulaOCRService().recognize_formula(submission)
                if formula_latex:
                    result.formula_latex = formula_latex
            except Exception as exc:
                warnings.append(f"{settings.formula_ocr_provider} formula OCR fallback: {exc}")

        result.warnings = [*(result.warnings or []), *warnings]
        return result

    def _unavailable_result(self, submission: Submission, exc: Exception) -> OCRResult:
        if isinstance(exc, LLMHTTPError) and exc.status_code == 401:
            message = (
                "Kimi/大模型认证失败：API Key 无效、已过期、未启用当前模型，或 Base URL 与账号不匹配。"
                "请检查 .env 中的 KIMI_API_KEY、LLM_BASE_URL、LLM_MODEL 和 LLM_VISION_MODEL，修改后重启服务。"
            )
            engine = "LLMAuthFailed"
        elif isinstance(exc, LLMHTTPError):
            message = (
                f"大模型服务返回 HTTP {exc.status_code}：{exc.body[:360]}。"
                "请检查模型是否支持图片、请求参数、额度和图片大小。Kimi 视觉建议使用 LLM_VISION_MODEL=kimi-k2.5。"
            )
            engine = "LLMRequestFailed"
        else:
            message = f"真实 OCR/视觉模型不可用：{exc}"
            engine = "OCRUnavailable"
        return OCRResult(
            raw_text="",
            confidence=0,
            blocks=[],
            engine=engine,
            warnings=[message],
        )

    def _recognize_with_llm_vision(self, submission: Submission, assignment: Assignment) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Vision LLM OCR requires an uploaded image")
        llm_result = LLMClient().extract_homework_text(
            image_path=image_path,
            subject=submission.subject,
            question_type=submission.question_type,
            assignment=assignment,
        )
        ocr_text = str(
            llm_result.data.get("ocr_text")
            or llm_result.data.get("student_answer")
            or llm_result.raw_text
            or ""
        ).strip()
        confidence = _safe_float(llm_result.data.get("confidence"), 0.75)
        warnings = llm_result.data.get("warnings") if isinstance(llm_result.data.get("warnings"), list) else []
        return OCRResult(
            raw_text=ocr_text,
            confidence=confidence,
            blocks=[
                {
                    "type": "llm_vision",
                    "text": ocr_text,
                    "confidence": confidence,
                    "detected_question": llm_result.data.get("detected_question", ""),
                }
            ],
            engine=f"VisionLLM:{llm_result.provider}:{llm_result.model}",
            warnings=warnings,
        )

    def _recognize_with_paddle(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("PaddleOCR requires an uploaded image")
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            raise RuntimeError("paddleocr package is not installed") from exc

        engine = PaddleOCR(use_angle_cls=True, lang="ch")
        rows = engine.ocr(str(image_path), cls=True)
        blocks: list[dict] = []
        texts: list[str] = []
        confidences: list[float] = []
        for page in rows or []:
            for item in page or []:
                text = item[1][0]
                confidence = float(item[1][1])
                texts.append(text)
                confidences.append(confidence)
                blocks.append({"type": "text", "text": text, "confidence": confidence, "box": item[0]})
        return OCRResult(
            raw_text="\n".join(texts),
            confidence=sum(confidences) / len(confidences) if confidences else 0,
            blocks=blocks,
            engine="PaddleOCR",
        )

    def _recognize_with_baidu(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Baidu OCR requires an uploaded image")
        if not settings.baidu_ocr_api_key or not settings.baidu_ocr_secret_key:
            raise RuntimeError("BAIDU_OCR_API_KEY and BAIDU_OCR_SECRET_KEY are required")

        token_url = "https://aip.baidubce.com/oauth/2.0/token"
        token_params = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": settings.baidu_ocr_api_key,
                "client_secret": settings.baidu_ocr_secret_key,
            }
        )
        token_data = _post_form(f"{token_url}?{token_params}", {})
        access_token = token_data["access_token"]

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting?access_token={access_token}"
        data = _post_form(url, {"image": image_b64})
        words = data.get("words_result", [])
        texts = [item.get("words", "") for item in words]
        return OCRResult(
            raw_text="\n".join(texts),
            confidence=0.9 if texts else 0,
            blocks=[{"type": "line", "text": text, "confidence": 0.9} for text in texts],
            engine="Baidu Handwriting OCR",
        )

    def _recognize_with_tencent(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Tencent OCR requires an uploaded image")
        if not settings.tencent_secret_id or not settings.tencent_secret_key:
            raise RuntimeError("TENCENT_SECRET_ID and TENCENT_SECRET_KEY are required")
        try:
            from tencentcloud.common import credential  # type: ignore
            from tencentcloud.common.profile.client_profile import ClientProfile  # type: ignore
            from tencentcloud.common.profile.http_profile import HttpProfile  # type: ignore
            from tencentcloud.ocr.v20181119 import models, ocr_client  # type: ignore
        except ImportError as exc:
            raise RuntimeError("tencentcloud-sdk-python package is not installed") from exc

        cred = credential.Credential(settings.tencent_secret_id, settings.tencent_secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "ocr.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = ocr_client.OcrClient(cred, settings.tencent_region, client_profile)
        req = models.GeneralHandwritingOCRRequest()
        req.ImageBase64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        resp = client.GeneralHandwritingOCR(req)
        data = json.loads(resp.to_json_string())
        items = data.get("TextDetections", [])
        texts = [item.get("DetectedText", "") for item in items]
        return OCRResult(
            raw_text="\n".join(texts),
            confidence=0.9 if texts else 0,
            blocks=[{"type": "line", "text": text, "confidence": 0.9} for text in texts],
            engine="Tencent GeneralHandwritingOCR",
        )

    def _mock_recognize(self, submission: Submission, assignment: Assignment) -> OCRResult:
        subject = submission.subject
        file_hint = (submission.image_name or "").lower()

        if subject == "数学":
            if any(token in file_hint for token in ["wrong", "partial", "error", "错"]):
                raw_text = "2x = 7 - 3\n2x = 5\nx = 2.5"
                confidence = 0.88
            elif assignment.question_type == "应用题":
                raw_text = "设每支笔 x 元。\n2x + 3 = 7\n2x = 4\nx = 2\n答：每支笔 2 元。"
                confidence = 0.91
            else:
                raw_text = "2x = 7 - 3\n2x = 4\nx = 2"
                confidence = 0.93
            return OCRResult(
                raw_text=raw_text,
                confidence=confidence,
                formula_latex=r"2x + 3 = 7, x = 2",
                blocks=[{"type": "formula", "text": "2x + 3 = 7", "confidence": 0.94}]
                + [
                    {"type": "step", "text": line, "confidence": confidence}
                    for line in raw_text.splitlines()
                ],
                engine="MockOCR",
            )

        if subject == "英语":
            raw_text = "I go to park with my friend. We play football. I very happy."
            return OCRResult(
                raw_text=raw_text,
                confidence=0.9,
                blocks=[
                    {"type": "sentence", "text": sentence.strip(), "confidence": 0.9}
                    for sentence in raw_text.split(".")
                    if sentence.strip()
                ],
                engine="MockOCR",
            )

        raw_text = "这次校园运动会让我印象很深。接力比赛时，同学们互相鼓励，我感受到集体的力量。"
        return OCRResult(
            raw_text=raw_text,
            confidence=0.89,
            blocks=[{"type": "paragraph", "text": raw_text, "confidence": 0.89}],
            engine="MockOCR",
        )


class FormulaOCRService:
    def recognize_formula(self, submission: Submission) -> str | None:
        provider = settings.formula_ocr_provider
        if provider == "mock":
            return r"2x + 3 = 7, x = 2"
        if provider == "mathpix":
            return self._mathpix(submission)
        if provider == "pix2tex":
            return self._pix2tex(submission)
        if provider in {"latex-ocr", "latex_ocr"}:
            return self._latex_ocr(submission)
        return None

    def _mathpix(self, submission: Submission) -> str:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Mathpix requires an uploaded image")
        if not settings.mathpix_app_id or not settings.mathpix_app_key:
            raise RuntimeError("MATHPIX_APP_ID and MATHPIX_APP_KEY are required")
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        payload = {
            "src": f"data:image/{image_path.suffix.lstrip('.')};base64,{image_b64}",
            "formats": ["text", "latex_styled"],
        }
        req = urllib.request.Request(
            "https://api.mathpix.com/v3/text",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "app_id": settings.mathpix_app_id,
                "app_key": settings.mathpix_app_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("latex_styled") or data.get("text") or ""

    def _pix2tex(self, submission: Submission) -> str:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("pix2tex requires an uploaded image")
        try:
            from PIL import Image  # type: ignore
            from pix2tex.cli import LatexOCR  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pix2tex and pillow packages are required") from exc
        model = LatexOCR()
        return model(Image.open(image_path))

    def _latex_ocr(self, submission: Submission) -> str:
        return self._pix2tex(submission)


def _submission_image_path(submission: Submission) -> Path | None:
    if not submission.image_url:
        return None
    name = submission.image_url.rsplit("/", 1)[-1]
    path = UPLOAD_DIR / name
    return path if path.exists() else None


def _post_form(url: str, payload: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
