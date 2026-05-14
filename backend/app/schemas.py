from typing import Any, Optional

from pydantic import BaseModel, Field


class UploadRequest(BaseModel):
    student_id: int
    subject: str
    question_type: str
    assignment_id: Optional[int] = None
    image_name: str = ""
    image_data: str = Field("", description="Data URL or base64 encoded image content.")
    essay_prompt: str = ""


class BatchImageItem(BaseModel):
    page_index: int
    image_name: str = ""
    image_data: str = Field("", description="Data URL or base64 encoded image content.")


class BatchUploadRequest(BaseModel):
    student_id: int
    subject: str
    question_type: str
    assignment_id: Optional[int] = None
    essay_prompt: str = ""
    images: list[BatchImageItem]


class BatchPageRequest(BaseModel):
    page_index: int
    image_url: str
    filename: str = ""
    image_name: str = ""


class BatchOCRRequest(BaseModel):
    batch_id: str
    submission_id: Optional[int] = None
    subject: str
    question_type: str
    pages: list[BatchPageRequest]


class BatchGradeRequest(BaseModel):
    batch_id: str
    submission_id: Optional[int] = None
    student_id: Optional[int] = None
    subject: str
    question_type: str
    merged_ocr_text: str = ""
    questions: list[dict] = Field(default_factory=list)
    page_results: list[dict] = Field(default_factory=list)
    essay_prompt: str = ""


class AssignmentCreateRequest(BaseModel):
    title: str
    subject: str
    question_type: str
    question: str
    standard_answer: str = ""
    full_score: float = 10
    knowledge_points: list[str] = Field(default_factory=list)


class ClassCreateRequest(BaseModel):
    name: str
    grade: str = ""
    teacher_name: str = ""


class DemoResetRequest(BaseModel):
    confirm: str = ""


class BulkUploadItem(BaseModel):
    student_id: int
    assignment_id: int
    image_name: str = ""
    image_data: str = ""


class BulkUploadRequest(BaseModel):
    items: list[BulkUploadItem]
    auto_ocr: bool = True
    auto_grade: bool = True


class AnnotationRequest(BaseModel):
    teacher_id: Optional[int] = None
    label: str
    comment: str = ""
    corrected_score: Optional[float] = None


class OCRRequest(BaseModel):
    submission_id: int
    force_demo_fixed_math_paper: bool = False


class GradeRequest(BaseModel):
    submission_id: int
    subject: Optional[str] = None
    question_type: Optional[str] = None
    ocr_text: Optional[str] = None
    essay_prompt: Optional[str] = None


class ReviewRequest(BaseModel):
    teacher_score: Optional[float] = None
    comment: Optional[str] = None
    review_note: Optional[str] = None
    action: str = "confirm"


class ApiResponse(BaseModel):
    data: Any
