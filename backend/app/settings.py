from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_api_token: str = os.getenv("APP_API_TOKEN", "")

    ocr_provider: str = os.getenv("OCR_PROVIDER", "mock").lower()
    ocr_fallback_to_mock: bool = _bool_env("OCR_FALLBACK_TO_MOCK", True)
    allow_mock_for_uploaded_images: bool = _bool_env("ALLOW_MOCK_FOR_UPLOADED_IMAGES", False)

    baidu_ocr_api_key: str = os.getenv("BAIDU_OCR_API_KEY", "")
    baidu_ocr_secret_key: str = os.getenv("BAIDU_OCR_SECRET_KEY", "")

    tencent_secret_id: str = os.getenv("TENCENT_SECRET_ID", "")
    tencent_secret_key: str = os.getenv("TENCENT_SECRET_KEY", "")
    tencent_region: str = os.getenv("TENCENT_REGION", "ap-guangzhou")

    formula_ocr_provider: str = os.getenv("FORMULA_OCR_PROVIDER", "mock").lower()
    mathpix_app_id: str = os.getenv("MATHPIX_APP_ID", "")
    mathpix_app_key: str = os.getenv("MATHPIX_APP_KEY", "")

    llm_enabled: bool = _bool_env("LLM_ENABLED", False)
    llm_provider: str = os.getenv("LLM_PROVIDER", "rule").lower()
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "40"))
    llm_fallback_to_rule: bool = _bool_env("LLM_FALLBACK_TO_RULE", True)
    llm_vision_enabled: bool = _bool_env("LLM_VISION_ENABLED", True)
    llm_vision_model: str = os.getenv("LLM_VISION_MODEL", "")
    llm_vision_ocr: bool = _bool_env("LLM_VISION_OCR", True)
    llm_grade_from_image: bool = _bool_env("LLM_GRADE_FROM_IMAGE", True)


settings = Settings()
