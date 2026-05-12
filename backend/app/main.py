from __future__ import annotations

import base64
import binascii
import io
import json
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
    BatchGradeRequest,
    BatchOCRRequest,
    BatchUploadRequest,
    BulkUploadRequest,
    ClassCreateRequest,
    DemoResetRequest,
    GradeRequest,
    OCRRequest,
    ReviewRequest,
    UploadRequest,
)
from .seed import seed_data
from .services.grading import GradingService
from .services.evaluation import EvaluationService
from .services.ocr import OCRService
from .services.ocr import demo_math_paper_ocr_data
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

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BATCH_PAGES = 10


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
def reset_demo_data(payload: DemoResetRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    client_host = request.client.host if request.client else ""
    is_local = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if not is_local and not settings.demo_fixed_math_paper_ocr:
        raise HTTPException(status_code=403, detail="演示数据重置仅允许在本地或比赛演示模式下使用")
    if payload.confirm != "RESET_DEMO_DATA":
        raise HTTPException(status_code=400, detail="请确认操作：该操作会清空测试提交记录。")

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
        pages=[],
        essay_prompt=payload.essay_prompt.strip(),
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


@app.post("/api/upload/batch")
def upload_homework_batch(
    payload: BatchUploadRequest,
    _: None = Depends(require_api_token),
    db: Session = Depends(get_db),
) -> dict:
    if not payload.images:
        raise HTTPException(status_code=400, detail="请至少上传一张图片")
    if len(payload.images) > MAX_BATCH_PAGES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_BATCH_PAGES} 张图片")

    student = db.get(User, payload.student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=404, detail="学生不存在")

    assignment = _resolve_assignment(db, payload)
    batch_id = f"batch_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    pages: list[dict] = []
    for index, item in enumerate(payload.images, start=1):
        page_index = item.page_index or index
        image_url = _save_image(item.image_data, item.image_name)
        filename = image_url.rsplit("/", 1)[-1] if image_url else ""
        pages.append(
            {
                "page_index": page_index,
                "filename": filename,
                "image_url": image_url,
                "image_name": item.image_name,
            }
        )

    pages.sort(key=lambda page: int(page.get("page_index") or 0))
    first_page = pages[0] if pages else {}
    submission = Submission(
        student_id=student.id,
        assignment_id=assignment.id,
        subject=payload.subject,
        question_type=payload.question_type,
        image_url=first_page.get("image_url") or "",
        image_name=first_page.get("image_name") or first_page.get("filename") or "",
        batch_id=batch_id,
        pages=pages,
        essay_prompt=payload.essay_prompt.strip(),
        status="待批改",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    return {
        "data": {
            "submission_id": submission.id,
            "batch_id": batch_id,
            "pages": pages,
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


@app.post("/api/ocr/batch")
def run_ocr_batch(payload: BatchOCRRequest, db: Session = Depends(get_db)) -> dict:
    submission = _get_batch_submission(db, payload.batch_id, payload.submission_id)
    assignment = submission.assignment
    ordered_pages = sorted([_pydantic_dict(page) for page in payload.pages], key=lambda page: int(page.get("page_index") or 0))
    if not ordered_pages:
        raise HTTPException(status_code=400, detail="批量 OCR 至少需要一页图片")

    page_results: list[dict] = []
    if settings.demo_fixed_math_paper_ocr and _is_answer_sheet_mode(payload.subject, payload.question_type, assignment):
        page_results = _demo_batch_page_results(ordered_pages)
    else:
        for page in ordered_pages:
            temp_submission = Submission(
                id=(submission.id or 0) * 100 + int(page.get("page_index") or 0),
                student_id=submission.student_id,
                assignment_id=submission.assignment_id,
                subject=payload.subject,
                question_type=payload.question_type,
                image_url=page.get("image_url") or "",
                image_name=page.get("image_name") or page.get("filename") or "",
            )
            result = ocr_service.recognize(temp_submission, assignment)
            page_results.append(
                {
                    "page_index": page.get("page_index"),
                    "image_url": page.get("image_url"),
                    "filename": page.get("filename") or (page.get("image_url") or "").rsplit("/", 1)[-1],
                    "ocr_text": result.raw_text,
                    "confidence": result.confidence,
                    "engine": result.engine,
                    "warnings": result.warnings or [],
                    "blocks": result.blocks,
                }
            )

    merged = merge_ocr_pages(page_results, payload.subject, payload.question_type)
    ocr_payload = {
        "batch_id": payload.batch_id,
        "subject": payload.subject,
        "question_type": payload.question_type,
        **merged,
    }
    submission.pages = _merge_page_metadata(ordered_pages, page_results)
    submission.ocr_text = json_dumps_utf8(ocr_payload)
    submission.ocr_engine = "BatchOCR"
    submission.ocr_confidence = _average_confidence(page_results)
    submission.ocr_warnings = [warning for page in page_results for warning in page.get("warnings", [])]
    db.commit()
    db.refresh(submission)
    return {
        "data": {
            "submission_id": submission.id,
            "batch_id": payload.batch_id,
            **ocr_payload,
            "submission": _submission_to_dict(submission),
        }
    }


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
    essay_prompt = (payload.essay_prompt if payload.essay_prompt is not None else submission.essay_prompt) or ""
    if payload.essay_prompt is not None:
        submission.essay_prompt = essay_prompt.strip()
    grading = grading_service.grade(
        subject,
        question_type,
        ocr_text,
        submission.assignment,
        image_path=_submission_image_path(submission),
        essay_prompt=essay_prompt,
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


@app.post("/api/grade/batch")
def run_grade_batch(payload: BatchGradeRequest, db: Session = Depends(get_db)) -> dict:
    submission = _get_batch_submission(db, payload.batch_id, payload.submission_id)
    subject = payload.subject or submission.subject
    question_type = payload.question_type or submission.question_type
    essay_prompt = (payload.essay_prompt or submission.essay_prompt or "").strip()
    if essay_prompt:
        submission.essay_prompt = essay_prompt

    merged_payload = {
        "batch_id": payload.batch_id,
        "subject": subject,
        "question_type": question_type,
        "page_results": payload.page_results,
        "merged_ocr_text": payload.merged_ocr_text,
        "questions": payload.questions,
        "essay_prompt": essay_prompt,
    }
    ocr_text = json_dumps_utf8(merged_payload)
    grading = grading_service.grade_batch(
        subject=subject,
        question_type=question_type,
        merged_ocr_text=payload.merged_ocr_text,
        questions=payload.questions,
        assignment=submission.assignment,
        page_results=payload.page_results,
        essay_prompt=essay_prompt,
    )

    submission.ai_score = grading["score"]
    submission.status = "AI 已批改"
    submission.ocr_text = ocr_text
    submission.ocr_engine = submission.ocr_engine or "BatchOCR"

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


def merge_ocr_pages(page_results: list[dict], subject: str, question_type: str) -> dict:
    ordered = sorted(page_results, key=lambda page: int(page.get("page_index") or 0))
    merged_ocr_text = "\n\n".join(
        f"【第{page.get('page_index')}页】\n{page.get('ocr_text', '').strip()}"
        for page in ordered
        if page.get("ocr_text")
    )

    structured_questions = _questions_from_structured_pages(ordered)
    if structured_questions:
        questions = structured_questions
    else:
        questions = _merge_numbered_blocks(ordered)

    warnings = [question.get("merge_warning") for question in questions if question.get("merge_warning")]
    review_count = sum(1 for question in questions if question.get("merge_status") != "已合并")
    return {
        "page_results": ordered,
        "merged_ocr_text": merged_ocr_text,
        "questions": questions,
        "merge_summary": {
            "page_count": len(ordered),
            "question_count": len(questions),
            "merged": bool(questions),
            "review_count": review_count,
            "warnings": warnings,
        },
    }


def _questions_from_structured_pages(page_results: list[dict]) -> list[dict]:
    for page in page_results:
        structured = page.get("structured")
        questions = structured.get("questions") if isinstance(structured, dict) else None
        if isinstance(questions, list) and questions:
            normalized_questions = [
                {
                    "question_no": item.get("question_no"),
                    "question_text": item.get("question_text", ""),
                    "student_answer": item.get("student_answer", ""),
                    "source_pages": item.get("source_pages") or [page.get("page_index")],
                    "confidence": item.get("confidence", page.get("confidence", 0.85)),
                    "merge_status": item.get("merge_status") or _merge_status(float(item.get("confidence", page.get("confidence", 0.85)) or 0), item.get("merge_warning", "")),
                    "merge_warning": item.get("merge_warning", ""),
                }
                for item in questions
                if isinstance(item, dict)
            ]
            return normalized_questions
    return []


def _merge_numbered_blocks(page_results: list[dict]) -> list[dict]:
    bucket: dict[str, dict] = {}
    for page in page_results:
        page_index = int(page.get("page_index") or 0)
        blocks = _extract_numbered_blocks(page.get("ocr_text") or "")
        for number, body in blocks:
            item = bucket.setdefault(number, {"question_no": number, "question_candidates": [], "answer_candidates": [], "source_pages": []})
            item["source_pages"].append(page_index)
            question_text, answer_text = _split_question_and_answer(body)
            if question_text:
                item["question_candidates"].append({"text": question_text, "page": page_index})
            if answer_text:
                item["answer_candidates"].append({"text": answer_text, "page": page_index})

    questions: list[dict] = []
    for number in sorted(bucket, key=lambda value: int(value) if str(value).isdigit() else 999):
        item = bucket[number]
        question_text = _pick_question_text(item["question_candidates"])
        answer_text = _pick_answer_text(item["answer_candidates"])
        confidence = _merge_confidence(question_text, answer_text, item["source_pages"])
        warning = "" if question_text and answer_text else "题号匹配不完整，建议教师复核"
        questions.append(
            {
                "question_no": int(number) if str(number).isdigit() else number,
                "question_text": question_text,
                "student_answer": answer_text,
                "source_pages": sorted(set(item["source_pages"])),
                "confidence": confidence,
                "merge_status": _merge_status(confidence, warning),
                "merge_warning": warning,
            }
        )
    return questions


def _merge_confidence(question_text: str, answer_text: str, source_pages: list[int]) -> float:
    score = 0.35
    if question_text:
        score += 0.25
    if answer_text:
        score += 0.25
    if len(set(source_pages)) >= 2:
        score += 0.08
    if re.search(r"(答[:：]|=)", answer_text):
        score += 0.07
    return round(min(score, 0.98), 2)


def _merge_status(confidence: float, warning: str = "") -> str:
    if warning or confidence < 0.6:
        return "需要复核"
    if confidence < 0.8:
        return "低置信度"
    return "已合并"


def _extract_numbered_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^\s*(?:第\s*)?(\d+)\s*(?:[\.、．]|题[:：]?)\s*", text))
    if not matches:
        return []
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            blocks.append((match.group(1), body))
    return blocks


def _split_question_and_answer(body: str) -> tuple[str, str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return "", ""
    first = lines[0]
    rest = "\n".join(lines[1:]).strip()
    if _looks_like_question(first):
        return first, rest
    if rest and _looks_like_question(body):
        return first, rest
    return "", "\n".join(lines)


def _looks_like_question(text: str) -> bool:
    return bool(
        re.search(
            r"(计算|解方程|应用题|求|多少钱|作文|写作|阅读|简答|Write|passage|essay|[？?])",
            text,
            flags=re.I,
        )
    )


def _pick_question_text(candidates: list[dict]) -> str:
    if not candidates:
        return ""
    candidates = sorted(candidates, key=lambda item: (0 if _looks_like_question(item["text"]) else 1, len(item["text"])))
    return candidates[0]["text"]


def _pick_answer_text(candidates: list[dict]) -> str:
    if not candidates:
        return ""
    return "\n".join(item["text"] for item in sorted(candidates, key=lambda item: item.get("page") or 0) if item.get("text")).strip()


def _demo_batch_page_results(pages: list[dict]) -> list[dict]:
    paper = demo_math_paper_ocr_data()
    questions = paper["questions"]
    question_lines = [paper["paper_title"]]
    answer_lines = ["学生答题过程"]
    for question in questions:
        question_lines.append(f"{question['question_no']}. {question['question_text']}")
        answer_lines.append(f"{question['question_no']}. " + "\n".join(question["student_answer"]))

    page_texts = [("\n".join(question_lines), 0.99), ("\n\n".join(answer_lines), 0.99)]
    results: list[dict] = []
    for index, page in enumerate(pages):
        text, confidence = page_texts[index] if index < len(page_texts) else ("", 0.5)
        results.append(
            {
                "page_index": page.get("page_index") or index + 1,
                "image_url": page.get("image_url"),
                "filename": page.get("filename") or (page.get("image_url") or "").rsplit("/", 1)[-1],
                "ocr_text": text,
                "confidence": confidence,
                "engine": "DemoBatchMathPaperOCR",
                "warnings": ["比赛稳定演示模式：已按多图顺序返回题目页和答题页 OCR。"],
                "blocks": [],
            }
        )
    return results


def _merge_page_metadata(pages: list[dict], page_results: list[dict]) -> list[dict]:
    result_by_index = {int(item.get("page_index") or 0): item for item in page_results}
    merged: list[dict] = []
    for page in pages:
        index = int(page.get("page_index") or 0)
        result = result_by_index.get(index, {})
        merged.append(
            {
                **page,
                "ocr_engine": result.get("engine"),
                "ocr_confidence": result.get("confidence"),
                "ocr_text": result.get("ocr_text", ""),
                "warnings": result.get("warnings", []),
            }
        )
    return merged


def _average_confidence(page_results: list[dict]) -> float:
    values = [float(item.get("confidence") or 0) for item in page_results]
    return round(sum(values) / len(values), 3) if values else 0


def _is_answer_sheet_mode(subject: str, question_type: str, assignment: Assignment) -> bool:
    return (
        subject in {"自动识别", "综合"}
        or question_type in {"答题卡", "整张答题卡", "自动识别"}
        or assignment.subject in {"自动识别", "综合"}
        or assignment.question_type in {"答题卡", "整张答题卡"}
    )


def json_dumps_utf8(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _pydantic_dict(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


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


def _get_batch_submission(db: Session, batch_id: str, submission_id: int | None = None) -> Submission:
    if submission_id:
        submission = db.get(Submission, submission_id)
    else:
        submission = db.query(Submission).filter(Submission.batch_id == batch_id).first()
    if not submission or submission.batch_id != batch_id:
        raise HTTPException(status_code=404, detail="批量提交记录不存在")
    return submission


def _save_image(image_data: str, image_name: str) -> str:
    if not image_data:
        return ""

    header = ""
    content = image_data
    if "," in image_data and image_data.startswith("data:"):
        header, content = image_data.split(",", 1)

    try:
        binary = base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="图片 base64 数据解析失败") from exc
    if len(binary) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片过大，请压缩到 8MB 以内。")

    extension = _validate_image_binary(binary, image_name, header)

    filename = f"{uuid.uuid4().hex}.{extension}"
    path = UPLOAD_DIR / filename
    path.write_bytes(binary)
    return f"/uploads/{filename}"


def _validate_image_binary(binary: bytes, image_name: str, header: str = "") -> str:
    declared = Path(image_name or "").suffix.lower().lstrip(".")
    if declared == "jpeg":
        declared = "jpg"
    if declared and declared not in {"jpg", "png"}:
        raise HTTPException(status_code=400, detail="图片格式无效，请上传 JPG / PNG / JPEG。")

    try:
        from PIL import Image  # type: ignore
    except ImportError:
        if binary.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if binary.startswith(b"\xff\xd8\xff"):
            return "jpg"
        raise HTTPException(status_code=400, detail="图片文件损坏，无法识别。")

    try:
        with Image.open(io.BytesIO(binary)) as image:
            image.verify()
            detected = (image.format or "").lower()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="图片文件损坏，无法识别。") from exc

    if detected not in {"jpeg", "png"}:
        raise HTTPException(status_code=400, detail="图片格式无效，请上传 JPG / PNG / JPEG。")
    detected_ext = "jpg" if detected == "jpeg" else "png"
    if declared and declared != detected_ext:
        raise HTTPException(status_code=400, detail="图片真实格式与文件扩展名不一致，请重新导出 JPG 或 PNG。")
    if header and "image/" in header and detected_ext not in header.replace("jpeg", "jpg"):
        raise HTTPException(status_code=400, detail="图片真实格式与上传声明不一致，请重新上传。")
    return detected_ext


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
        "batch_id": submission.batch_id,
        "pages": submission.pages or [],
        "essay_prompt": submission.essay_prompt or "",
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
