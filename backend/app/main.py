from __future__ import annotations

import base64
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .database import PROJECT_ROOT, UPLOAD_DIR, get_db, init_db
from .auth import require_api_token
from .models import Assignment, ClassRoom, GradingResult, Submission, TeacherAnnotation, User
from .schemas import (
    AnnotationRequest,
    AssignmentCreateRequest,
    BulkUploadRequest,
    ClassCreateRequest,
    GradeRequest,
    OCRRequest,
    ReviewRequest,
    UploadRequest,
)
from .seed import seed_data
from .services.grading import GradingService
from .services.evaluation import EvaluationService
from .services.ocr import OCRService
from .services.reports import ReportService
from .settings import settings
from .services.llm import _resolve_vision_model


app = FastAPI(
    title="希沃智评 API",
    description="多学科 AI 智能作业批改系统 Demo API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ocr_service = OCRService()
grading_service = GradingService()
evaluation_service = EvaluationService(grading_service)
report_service = ReportService()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    from .database import SessionLocal

    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "name": "希沃智评", "version": "1.0.0"}


@app.get("/api/runtime/status")
def runtime_status() -> dict:
    return {
        "data": {
            "ocr_provider": settings.ocr_provider,
            "ocr_fallback_to_mock": settings.ocr_fallback_to_mock,
            "allow_mock_for_uploaded_images": settings.allow_mock_for_uploaded_images,
            "demo_fixed_math_paper_ocr": settings.demo_fixed_math_paper_ocr,
            "ocr_preprocess_enabled": settings.ocr_preprocess_enabled,
            "ocr_preprocess_for_llm": settings.ocr_preprocess_for_llm,
            "ocr_preprocess_max_side": settings.ocr_preprocess_max_side,
            "llm_enabled": settings.llm_enabled,
            "llm_provider": settings.llm_provider,
            "llm_base_url": settings.llm_base_url,
            "llm_model": settings.llm_model,
            "llm_vision_enabled": settings.llm_vision_enabled,
            "llm_vision_model": settings.llm_vision_model,
            "effective_vision_model": _resolve_vision_model(settings.llm_provider, settings.llm_vision_model or settings.llm_model),
            "llm_has_key": bool(
                settings.llm_api_key
                or os.getenv("KIMI_API_KEY")
                or os.getenv("MOONSHOT_API_KEY")
                or os.getenv("DEEPSEEK_API_KEY")
            ),
        }
    }


@app.get("/api/evaluation/grading")
def grading_evaluation() -> dict:
    return {"data": evaluation_service.run_grading_benchmark()}


@app.post("/api/demo/reset", dependencies=[Depends(require_api_token)])
def reset_demo_data(request: Request, db: Session = Depends(get_db)) -> dict:
    client_host = request.client.host if request.client else ""
    is_local = client_host in {"127.0.0.1", "::1", "localhost"}
    if not is_local and not settings.demo_fixed_math_paper_ocr:
        raise HTTPException(status_code=403, detail="演示数据重置仅允许在本地或比赛演示模式下使用")

    submission_count = db.query(Submission).count()
    annotation_count = db.query(TeacherAnnotation).count()
    grading_count = db.query(GradingResult).count()
    for submission in db.query(Submission).all():
        db.delete(submission)
    db.commit()
    seed_data(db)
    restored = db.query(Submission).count()
    return {
        "data": {
            "message": "演示数据已重置",
            "deleted_submissions": submission_count,
            "deleted_grading_results": grading_count,
            "deleted_annotations": annotation_count,
            "restored_demo_submissions": restored,
        }
    }


@app.get("/api/students")
def list_students(db: Session = Depends(get_db)) -> dict:
    students = db.query(User).filter(User.role == "student").order_by(User.id).all()
    return {"data": [_user_to_dict(student) for student in students]}


@app.get("/api/assignments")
def list_assignments(subject: str | None = None, db: Session = Depends(get_db)) -> dict:
    query = db.query(Assignment)
    if subject:
        query = query.filter(Assignment.subject == subject)
    assignments = query.order_by(Assignment.id).all()
    return {"data": [_assignment_to_dict(item) for item in assignments]}


@app.post("/api/question-bank", dependencies=[Depends(require_api_token)])
def create_assignment(payload: AssignmentCreateRequest, db: Session = Depends(get_db)) -> dict:
    assignment = Assignment(
        title=payload.title,
        subject=payload.subject,
        question_type=payload.question_type,
        question=payload.question,
        standard_answer=payload.standard_answer,
        full_score=payload.full_score,
        knowledge_points=payload.knowledge_points,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return {"data": _assignment_to_dict(assignment)}


@app.get("/api/question-bank")
def list_question_bank(subject: str | None = None, db: Session = Depends(get_db)) -> dict:
    return list_assignments(subject=subject, db=db)


@app.get("/api/classes")
def list_classes(db: Session = Depends(get_db)) -> dict:
    classes = db.query(ClassRoom).order_by(ClassRoom.id).all()
    return {"data": [_class_to_dict(item) for item in classes]}


@app.post("/api/classes", dependencies=[Depends(require_api_token)])
def create_classroom(payload: ClassCreateRequest, db: Session = Depends(get_db)) -> dict:
    existing = db.query(ClassRoom).filter(ClassRoom.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="班级已存在")
    classroom = ClassRoom(name=payload.name, grade=payload.grade, teacher_name=payload.teacher_name)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return {"data": _class_to_dict(classroom)}


@app.post("/api/upload")
def upload_homework(
    payload: UploadRequest,
    _: None = Depends(require_api_token),
    db: Session = Depends(get_db),
) -> dict:
    student = db.get(User, payload.student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="学生不存在")

    assignment = _resolve_assignment(db, payload)
    image_url = _save_image(payload.image_data, payload.image_name)

    submission = Submission(
        student_id=student.id,
        assignment_id=assignment.id,
        subject=payload.subject,
        question_type=payload.question_type,
        image_url=image_url,
        image_name=payload.image_name,
        status="待批改",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    return {
        "data": {
            "submission_id": submission.id,
            "image_url": submission.image_url,
            "status": submission.status,
            "assignment": _assignment_to_dict(assignment),
        }
    }


@app.post("/api/bulk-upload")
def bulk_upload(
    payload: BulkUploadRequest,
    _: None = Depends(require_api_token),
    db: Session = Depends(get_db),
) -> dict:
    created: list[dict] = []
    for item in payload.items:
        student = db.get(User, item.student_id)
        assignment = db.get(Assignment, item.assignment_id)
        if not student or student.role != "student" or not assignment:
            raise HTTPException(status_code=404, detail="批量上传中存在无效学生或作业")
        submission = Submission(
            student_id=student.id,
            assignment_id=assignment.id,
            subject=assignment.subject,
            question_type=assignment.question_type,
            image_url=_save_image(item.image_data, item.image_name),
            image_name=item.image_name,
            status="待批改",
        )
        db.add(submission)
        db.flush()
        if payload.auto_ocr:
            ocr_result = ocr_service.recognize(submission, assignment)
            submission.ocr_text = ocr_result.raw_text
            submission.ocr_engine = ocr_result.engine
            submission.ocr_confidence = ocr_result.confidence
            submission.ocr_warnings = ocr_result.warnings or []
        if payload.auto_grade:
            if not submission.ocr_text:
                ocr_result = ocr_service.recognize(submission, assignment)
                submission.ocr_text = ocr_result.raw_text
                submission.ocr_engine = ocr_result.engine
                submission.ocr_confidence = ocr_result.confidence
                submission.ocr_warnings = ocr_result.warnings or []
            grading = grading_service.grade(
                assignment.subject,
                assignment.question_type,
                submission.ocr_text or "",
                assignment,
                image_path=_submission_image_path(submission),
            )
            submission.ai_score = grading["score"]
            submission.status = "AI 已批改"
            db.add(GradingResult(submission_id=submission.id, **_grading_payload(grading)))
        created.append({"submission_id": submission.id, "student_name": student.name, "assignment_title": assignment.title})
    db.commit()
    return {"data": {"created": created, "count": len(created)}}


@app.post("/api/ocr")
def run_ocr(payload: OCRRequest, db: Session = Depends(get_db)) -> dict:
    submission = _get_submission(db, payload.submission_id)
    result = ocr_service.recognize(submission, submission.assignment)
    submission.ocr_text = result.raw_text
    submission.ocr_engine = result.engine
    submission.ocr_confidence = result.confidence
    submission.ocr_warnings = result.warnings or []
    db.commit()
    db.refresh(submission)
    return {"data": {"submission_id": submission.id, "ocr": result.to_dict(), "submission": _submission_to_dict(submission)}}


@app.post("/api/grade")
def run_grade(payload: GradeRequest, db: Session = Depends(get_db)) -> dict:
    submission = _get_submission(db, payload.submission_id)
    ocr_text = payload.ocr_text or submission.ocr_text
    if not ocr_text:
        result = ocr_service.recognize(submission, submission.assignment)
        ocr_text = result.raw_text
        submission.ocr_text = result.raw_text

    subject = payload.subject or submission.subject
    question_type = payload.question_type or submission.question_type
    grading = grading_service.grade(
        subject,
        question_type,
        ocr_text,
        submission.assignment,
        image_path=_submission_image_path(submission),
    )

    submission.ai_score = grading["score"]
    submission.status = "AI 已批改"
    submission.ocr_text = ocr_text

    existing = submission.grading_result
    if existing:
        _fill_grading_result(existing, grading)
    else:
        db.add(GradingResult(submission_id=submission.id, **_grading_payload(grading)))

    db.commit()
    db.refresh(submission)
    return {"data": {"submission": _submission_to_dict(submission), "grading_result": _grading_to_dict(submission.grading_result)}}


@app.get("/api/submissions")
def list_submissions(db: Session = Depends(get_db)) -> dict:
    submissions = db.query(Submission).order_by(Submission.created_at.desc()).all()
    return {"data": [_submission_to_dict(submission) for submission in submissions]}


@app.get("/api/submissions/{submission_id}")
def get_submission_detail(submission_id: int, db: Session = Depends(get_db)) -> dict:
    submission = _get_submission(db, submission_id)
    return {"data": _submission_to_dict(submission, detail=True)}


@app.put("/api/submissions/{submission_id}/review")
def review_submission(
    submission_id: int,
    payload: ReviewRequest,
    _: None = Depends(require_api_token),
    db: Session = Depends(get_db),
) -> dict:
    submission = _get_submission(db, submission_id)
    result = submission.grading_result
    if not result:
        raise HTTPException(status_code=400, detail="该提交尚未完成 AI 批改")

    if payload.teacher_score is not None:
        if payload.teacher_score < 0 or payload.teacher_score > submission.assignment.full_score:
            raise HTTPException(status_code=400, detail="教师分数超出满分范围")
        submission.teacher_score = payload.teacher_score

    if payload.comment:
        result.comment = payload.comment
    if payload.review_note:
        result.review_note = payload.review_note

    submission.status = "已返回学生" if payload.action == "return" else "教师已复核"
    submission.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(submission)

    return {"data": _submission_to_dict(submission, detail=True)}


@app.post("/api/submissions/{submission_id}/annotations")
def create_annotation(
    submission_id: int,
    payload: AnnotationRequest,
    _: None = Depends(require_api_token),
    db: Session = Depends(get_db),
) -> dict:
    submission = _get_submission(db, submission_id)
    annotation = TeacherAnnotation(
        submission_id=submission.id,
        teacher_id=payload.teacher_id,
        label=payload.label,
        comment=payload.comment,
        corrected_score=payload.corrected_score,
    )
    if payload.corrected_score is not None:
        submission.teacher_score = payload.corrected_score
        submission.status = "教师已复核"
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return {"data": _annotation_to_dict(annotation)}


@app.get("/api/submissions/{submission_id}/annotations")
def list_annotations(submission_id: int, db: Session = Depends(get_db)) -> dict:
    submission = _get_submission(db, submission_id)
    return {"data": [_annotation_to_dict(item) for item in submission.annotations]}


@app.get("/api/students/{student_id}/report")
def get_student_report(student_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return {"data": report_service.student_report(db, student_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/classes/{class_name}/analysis")
def get_class_analysis(class_name: str, db: Session = Depends(get_db)) -> dict:
    return {"data": report_service.class_analysis(db, class_name)}


@app.get("/api/classes/{class_name}/analysis/export", response_class=PlainTextResponse)
def export_class_analysis(class_name: str, db: Session = Depends(get_db)) -> str:
    analysis = report_service.class_analysis(db, class_name)
    weak_lines = "\n".join(
        f"- {item['knowledge_point']}：{item['count']} 次，建议：{item['suggestion']}"
        for item in analysis["common_weak_points"]
    ) or "- 暂无集中薄弱点"
    mistake_lines = "\n".join(
        f"- {item['mistake']}（{item['count']} 次）" for item in analysis["frequent_mistakes"]
    ) or "- 暂无高频错误"
    return f"""# {class_name} 学情分析报告

## 核心指标
- 学生人数：{analysis['total_students']}
- 提交数量：{analysis['total_submissions']}
- 平均分：{analysis['average_score']}
- 最高分：{analysis['highest_score']}
- 最低分：{analysis['lowest_score']}
- 整体正确率：{analysis['accuracy_rate']}

## 高频薄弱知识点
{weak_lines}

## 高频错误
{mistake_lines}

## 教学建议
{analysis['teacher_suggestion']}
"""


def _resolve_assignment(db: Session, payload: UploadRequest) -> Assignment:
    if payload.assignment_id:
        assignment = db.get(Assignment, payload.assignment_id)
        if assignment:
            return assignment

    assignment = (
        db.query(Assignment)
        .filter(Assignment.subject == payload.subject, Assignment.question_type == payload.question_type)
        .first()
    )
    if assignment:
        return assignment

    assignment = db.query(Assignment).filter(Assignment.subject == payload.subject).first()
    if assignment:
        return assignment

    raise HTTPException(status_code=404, detail="未找到匹配作业")


def _get_submission(db: Session, submission_id: int) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    return submission


def _save_image(image_data: str, image_name: str) -> str:
    if not image_data:
        return ""

    header = ""
    content = image_data
    if "," in image_data and image_data.startswith("data:"):
        header, content = image_data.split(",", 1)

    extension = Path(image_name or "upload.png").suffix.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png"}:
        if "jpeg" in header:
            extension = "jpg"
        elif "png" in header:
            extension = "png"
        else:
            extension = "png"

    try:
        binary = base64.b64decode(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="图片 base64 数据解析失败") from exc

    filename = f"{uuid.uuid4().hex}.{extension}"
    path = UPLOAD_DIR / filename
    path.write_bytes(binary)
    return f"/uploads/{filename}"


def _submission_image_path(submission: Submission) -> Path | None:
    if not submission.image_url:
        return None
    filename = submission.image_url.rsplit("/", 1)[-1]
    path = UPLOAD_DIR / filename
    return path if path.exists() else None


def _grading_payload(grading: dict) -> dict:
    return {
        "is_correct": grading.get("is_correct", False),
        "process_analysis": grading.get("process_analysis"),
        "content_analysis": grading.get("content_analysis"),
        "structure_analysis": grading.get("structure_analysis"),
        "language_analysis": grading.get("language_analysis"),
        "mistakes": grading.get("mistakes") or [],
        "errors": grading.get("errors") or [],
        "strengths": grading.get("strengths") or [],
        "knowledge_points": grading.get("knowledge_points") or [],
        "weak_points": grading.get("weak_points") or [],
        "dimension_scores": grading.get("dimension_scores") or {},
        "correct_solution": grading.get("correct_solution"),
        "revised_example": grading.get("revised_example"),
        "comment": grading.get("comment"),
        "suggestion": grading.get("suggestion"),
        "ai_engine": grading.get("ai_engine"),
        "ai_metadata": grading.get("ai_metadata") or {},
    }


def _fill_grading_result(result: GradingResult, grading: dict) -> None:
    payload = _grading_payload(grading)
    for key, value in payload.items():
        setattr(result, key, value)


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "class_name": user.class_name,
    }


def _assignment_to_dict(assignment: Assignment) -> dict:
    return {
        "id": assignment.id,
        "title": assignment.title,
        "subject": assignment.subject,
        "question_type": assignment.question_type,
        "question": assignment.question,
        "standard_answer": assignment.standard_answer,
        "full_score": assignment.full_score,
        "knowledge_points": assignment.knowledge_points or [],
    }


def _class_to_dict(classroom: ClassRoom) -> dict:
    return {
        "id": classroom.id,
        "name": classroom.name,
        "grade": classroom.grade,
        "teacher_name": classroom.teacher_name,
        "created_at": classroom.created_at.isoformat() if classroom.created_at else "",
    }


def _annotation_to_dict(annotation: TeacherAnnotation) -> dict:
    return {
        "id": annotation.id,
        "submission_id": annotation.submission_id,
        "teacher_id": annotation.teacher_id,
        "teacher_name": annotation.teacher.name if annotation.teacher else "",
        "label": annotation.label,
        "comment": annotation.comment,
        "corrected_score": annotation.corrected_score,
        "created_at": annotation.created_at.isoformat() if annotation.created_at else "",
    }


def _grading_to_dict(result: GradingResult | None) -> dict | None:
    if not result:
        return None
    submission = result.submission
    answer_sheet = (result.ai_metadata or {}).get("answer_sheet") if isinstance(result.ai_metadata, dict) else None
    result_full_score = answer_sheet.get("full_score") if isinstance(answer_sheet, dict) and answer_sheet.get("full_score") is not None else None
    return {
        "id": result.id,
        "submission_id": result.submission_id,
        "score": submission.teacher_score if submission and submission.teacher_score is not None else (submission.ai_score if submission else None),
        "ai_score": submission.ai_score if submission else None,
        "teacher_score": submission.teacher_score if submission else None,
        "full_score": result_full_score if result_full_score is not None else (submission.assignment.full_score if submission and submission.assignment else None),
        "is_correct": result.is_correct,
        "process_analysis": result.process_analysis,
        "content_analysis": result.content_analysis,
        "structure_analysis": result.structure_analysis,
        "language_analysis": result.language_analysis,
        "mistakes": result.mistakes or [],
        "errors": result.errors or [],
        "strengths": result.strengths or [],
        "knowledge_points": result.knowledge_points or [],
        "weak_points": result.weak_points or [],
        "dimension_scores": result.dimension_scores or {},
        "correct_solution": result.correct_solution,
        "revised_example": result.revised_example,
        "comment": result.comment,
        "suggestion": result.suggestion,
        "review_note": result.review_note,
        "ai_engine": result.ai_engine,
        "ai_metadata": result.ai_metadata or {},
        "updated_at": result.updated_at.isoformat() if result.updated_at else "",
    }


def _submission_to_dict(submission: Submission, detail: bool = False) -> dict:
    assignment = submission.assignment
    result = submission.grading_result
    answer_sheet = (result.ai_metadata or {}).get("answer_sheet") if result and isinstance(result.ai_metadata, dict) else None
    grading_full_score = (
        answer_sheet.get("full_score")
        if isinstance(answer_sheet, dict) and answer_sheet.get("full_score") is not None
        else None
    )
    data = {
        "id": submission.id,
        "student": _user_to_dict(submission.student),
        "assignment": _assignment_to_dict(assignment),
        "subject": submission.subject,
        "question_type": submission.question_type,
        "image_url": submission.image_url,
        "image_name": submission.image_name,
        "ocr_text": submission.ocr_text,
        "ocr_engine": submission.ocr_engine,
        "ocr_confidence": submission.ocr_confidence,
        "ocr_warnings": submission.ocr_warnings or [],
        "ai_score": submission.ai_score,
        "teacher_score": submission.teacher_score,
        "effective_score": submission.teacher_score if submission.teacher_score is not None else submission.ai_score,
        "grading_full_score": grading_full_score,
        "status": submission.status,
        "created_at": submission.created_at.isoformat() if submission.created_at else "",
        "reviewed_at": submission.reviewed_at.isoformat() if submission.reviewed_at else "",
    }
    if detail:
        data["grading_result"] = _grading_to_dict(submission.grading_result)
        data["annotations"] = [_annotation_to_dict(item) for item in submission.annotations]
    else:
        data["is_correct"] = result.is_correct if result else False
        data["weak_points"] = result.weak_points if result else []
        data["comment"] = result.comment if result else ""
    return data


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)


frontend_dir = PROJECT_ROOT / "frontend"
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
