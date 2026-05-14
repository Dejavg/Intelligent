from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


@dataclass
class ImagePreprocessResult:
    path: Path
    warnings: list[str]
    metadata: dict[str, Any]


class OCRService:
    """OCR adapter with mock, PaddleOCR, Baidu OCR, and Tencent OCR slots."""

    def recognize(self, submission: Submission, assignment: Assignment) -> OCRResult:
        warnings: list[str] = []
        try:
            if settings.demo_fixed_math_paper_ocr and _is_demo_answer_sheet(submission, assignment):
                result = self._demo_math_paper_recognize()
            elif settings.ocr_provider in {"llm", "vision", "kimi"}:
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

    def recognize_demo_math_paper(self) -> OCRResult:
        return self._demo_math_paper_recognize()

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
        prepared = _prepare_image_for_ocr(image_path, submission, for_llm=True)
        llm_result = LLMClient().extract_homework_text(
            image_path=prepared.path,
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
                    "type": "image_preprocess",
                    "text": "图像预处理",
                    "confidence": 1,
                    "metadata": prepared.metadata,
                },
                {
                    "type": "llm_vision",
                    "text": ocr_text,
                    "confidence": confidence,
                    "detected_question": llm_result.data.get("detected_question", ""),
                }
            ],
            engine=f"VisionLLM:{llm_result.provider}:{llm_result.model}",
            warnings=[*prepared.warnings, *warnings],
        )

    def _recognize_with_paddle(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("PaddleOCR requires an uploaded image")
        prepared = _prepare_image_for_ocr(image_path, submission)
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as exc:
            raise RuntimeError("paddleocr package is not installed") from exc

        engine = PaddleOCR(use_angle_cls=True, lang="ch")
        rows = engine.ocr(str(prepared.path), cls=True)
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
            blocks=[{"type": "image_preprocess", "text": "图像预处理", "confidence": 1, "metadata": prepared.metadata}, *blocks],
            engine="PaddleOCR",
            warnings=prepared.warnings,
        )

    def _recognize_with_baidu(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Baidu OCR requires an uploaded image")
        prepared = _prepare_image_for_ocr(image_path, submission)
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

        image_b64 = base64.b64encode(prepared.path.read_bytes()).decode("utf-8")
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/handwriting?access_token={access_token}"
        data = _post_form(url, {"image": image_b64})
        words = data.get("words_result", [])
        texts = [item.get("words", "") for item in words]
        return OCRResult(
            raw_text="\n".join(texts),
            confidence=0.9 if texts else 0,
            blocks=[{"type": "image_preprocess", "text": "图像预处理", "confidence": 1, "metadata": prepared.metadata}]
            + [{"type": "line", "text": text, "confidence": 0.9} for text in texts],
            engine="Baidu Handwriting OCR",
            warnings=prepared.warnings,
        )

    def _recognize_with_tencent(self, submission: Submission) -> OCRResult:
        image_path = _submission_image_path(submission)
        if not image_path:
            raise RuntimeError("Tencent OCR requires an uploaded image")
        prepared = _prepare_image_for_ocr(image_path, submission)
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
        req.ImageBase64 = base64.b64encode(prepared.path.read_bytes()).decode("utf-8")
        resp = client.GeneralHandwritingOCR(req)
        data = json.loads(resp.to_json_string())
        items = data.get("TextDetections", [])
        texts = [item.get("DetectedText", "") for item in items]
        return OCRResult(
            raw_text="\n".join(texts),
            confidence=0.9 if texts else 0,
            blocks=[{"type": "image_preprocess", "text": "图像预处理", "confidence": 1, "metadata": prepared.metadata}]
            + [{"type": "line", "text": text, "confidence": 0.9} for text in texts],
            engine="Tencent GeneralHandwritingOCR",
            warnings=prepared.warnings,
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

    def _demo_math_paper_recognize(self) -> OCRResult:
        paper = demo_math_paper_ocr_data()
        question_blocks = [
            {
                "type": "question",
                "question_no": question["question_no"],
                "question_text": question["question_text"],
                "student_answer": question["student_answer"],
                "confidence": 0.99,
            }
            for question in paper["questions"]
        ]
        return OCRResult(
            raw_text=json.dumps(paper, ensure_ascii=False, indent=2),
            confidence=0.99,
            blocks=[
                {
                    "type": "paper",
                    "paper_title": paper["paper_title"],
                    "subject": paper["subject"],
                    "confidence": 0.99,
                },
                *question_blocks,
            ],
            engine="DemoMathPaperOCR",
            warnings=["比赛稳定演示模式：已使用固定 5 题数学试卷结构化 OCR，真实 OCR 可关闭 DEMO_FIXED_MATH_PAPER_OCR 后演示。"],
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


def _prepare_image_for_ocr(image_path: Path, submission: Submission, for_llm: bool = False) -> ImagePreprocessResult:
    if not settings.ocr_preprocess_enabled:
        return ImagePreprocessResult(
            path=image_path,
            warnings=[],
            metadata={"enabled": False, "used": False, "reason": "OCR_PREPROCESS_ENABLED=false"},
        )
    if for_llm and not settings.ocr_preprocess_for_llm:
        return ImagePreprocessResult(
            path=image_path,
            warnings=[],
            metadata={
                "enabled": True,
                "used": False,
                "reason": "视觉大模型默认使用原图；如需增强图可设置 OCR_PREPROCESS_FOR_LLM=true",
            },
        )

    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError:
        return ImagePreprocessResult(
            path=image_path,
            warnings=["图像预处理依赖 Pillow 未安装，已使用原图进入 OCR。"],
            metadata={"enabled": True, "used": False, "reason": "Pillow not installed"},
        )

    output_dir = UPLOAD_DIR / "_preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{submission.id or image_path.stem}_{image_path.stem}.png"
    operations: list[str] = []
    warnings: list[str] = []

    try:
        image = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
        original_size = image.size
        max_side = max(settings.ocr_preprocess_max_side, 600)
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side))
            operations.append(f"缩放至最长边 {max_side}px")

        gray = ImageOps.grayscale(image)
        operations.append("灰度化")
        enhanced = ImageOps.autocontrast(gray)
        operations.append("自动对比度增强")

        processed = enhanced
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            array = np.array(enhanced)
            denoised = cv2.fastNlMeansDenoising(array, None, 8, 7, 21)
            operations.append("轻量去噪")
            binary = cv2.adaptiveThreshold(
                denoised,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                15,
            )
            operations.append("自适应二值化")
            angle = _estimate_skew_angle(binary)
            if angle is not None and 0.3 <= abs(angle) <= 8:
                center = (binary.shape[1] // 2, binary.shape[0] // 2)
                matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
                binary = cv2.warpAffine(
                    binary,
                    matrix,
                    (binary.shape[1], binary.shape[0]),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )
                operations.append(f"倾斜矫正 {round(angle, 2)}°")
            processed = Image.fromarray(binary)
        except ImportError:
            warnings.append("OpenCV/Numpy 未安装，已跳过去噪、二值化和倾斜矫正。")

        processed.save(output_path, format="PNG", optimize=True)
        metadata = {
            "enabled": True,
            "used": True,
            "original_name": image_path.name,
            "processed_name": output_path.name,
            "original_size": {"width": original_size[0], "height": original_size[1]},
            "processed_size": {"width": processed.size[0], "height": processed.size[1]},
            "operations": operations,
        }
        if operations:
            warnings.insert(0, "图像预处理完成：" + "、".join(operations))
        return ImagePreprocessResult(path=output_path, warnings=warnings, metadata=metadata)
    except Exception as exc:
        return ImagePreprocessResult(
            path=image_path,
            warnings=[f"图像预处理失败，已使用原图进入 OCR：{exc}"],
            metadata={"enabled": True, "used": False, "reason": str(exc)},
        )


def _estimate_skew_angle(binary_image) -> float | None:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    inverted = cv2.bitwise_not(binary_image)
    coords = np.column_stack(np.where(inverted > 0))
    if len(coords) < 80:
        return None
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    return -float(angle)


def demo_math_paper_ocr_data() -> dict[str, Any]:
    return {
        "subject": "数学",
        "paper_title": "数学练习卷",
        "demo_fixed": True,
        "questions": [
            {
                "question_no": 1,
                "question_text": "计算：36 ÷ 4 + 5 × 2",
                "student_answer": ["36 ÷ 4 = 9", "5 × 2 = 10", "9 + 10 = 19", "答：19"],
            },
            {
                "question_no": 2,
                "question_text": "解方程：2x + 3 = 11",
                "student_answer": ["2x = 11 - 3", "2x = 8", "x = 4", "答：x = 4"],
            },
            {
                "question_no": 3,
                "question_text": "计算：15 × 6 - 28",
                "student_answer": ["15 × 6 = 90", "90 - 28 = 72", "答：72"],
            },
            {
                "question_no": 4,
                "question_text": "解方程：3x - 5 = 10",
                "student_answer": ["3x = 10 + 5", "3x = 15", "x = 4", "答：x = 4"],
            },
            {
                "question_no": 5,
                "question_text": "小明买了 3 支铅笔，每支 2 元，又买了 1 本笔记本 5 元，一共用了多少钱？",
                "student_answer": ["3 × 2 = 6（元）", "6 + 5 = 11（元）", "答：一共用了 11 元。"],
            },
        ],
    }


def _is_demo_answer_sheet(submission: Submission, assignment: Assignment) -> bool:
    return (
        submission.subject in {"自动识别", "综合"}
        or submission.question_type in {"答题卡", "整张答题卡"}
        or assignment.subject in {"自动识别", "综合"}
        or assignment.question_type in {"答题卡", "整张答题卡"}
    )


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
