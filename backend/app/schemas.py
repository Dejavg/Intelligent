from typing import Any, Optional

from pydantic import BaseModel, Field


class UploadRequest(BaseModel):
    student_id: int
    subject: str
    question_type: str
    assignment_id: Optional[int] = None
    image_name: str = ""
    image_data: str = Field("", description="Data URL or base64 encoded image content.")


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


class GradeRequest(BaseModel):
    submission_id: int
    subject: Optional[str] = None
    question_type: Optional[str] = None
    ocr_text: Optional[str] = None


class ReviewRequest(BaseModel):
    teacher_score: Optional[float] = None
    comment: Optional[str] = None
    review_note: Optional[str] = None
    action: str = "confirm"


class ApiResponse(BaseModel):
    data: Any
