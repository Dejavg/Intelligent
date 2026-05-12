from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    role = Column(String(20), nullable=False, default="student")
    class_name = Column(String(50), nullable=True)

    submissions = relationship("Submission", back_populates="student")


class ClassRoom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    grade = Column(String(30), nullable=True)
    teacher_name = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(120), nullable=False)
    subject = Column(String(20), nullable=False, index=True)
    question_type = Column(String(30), nullable=False, index=True)
    question = Column(Text, nullable=False)
    standard_answer = Column(Text, nullable=True)
    full_score = Column(Float, nullable=False, default=10)
    knowledge_points = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    submissions = relationship("Submission", back_populates="assignment")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    subject = Column(String(20), nullable=False)
    question_type = Column(String(30), nullable=False)
    image_url = Column(String(255), nullable=True)
    image_name = Column(String(255), nullable=True)
    batch_id = Column(String(80), nullable=True, index=True)
    pages = Column(JSON, nullable=False, default=list)
    essay_prompt = Column(Text, nullable=True)
    ocr_text = Column(Text, nullable=True)
    ocr_engine = Column(String(80), nullable=True)
    ocr_confidence = Column(Float, nullable=True)
    ocr_warnings = Column(JSON, nullable=False, default=list)
    ai_score = Column(Float, nullable=True)
    teacher_score = Column(Float, nullable=True)
    status = Column(String(30), nullable=False, default="待批改")
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    student = relationship("User", back_populates="submissions")
    assignment = relationship("Assignment", back_populates="submissions")
    grading_result = relationship(
        "GradingResult",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )
    annotations = relationship(
        "TeacherAnnotation",
        back_populates="submission",
        cascade="all, delete-orphan",
    )


class GradingResult(Base):
    __tablename__ = "grading_results"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, unique=True)
    is_correct = Column(Boolean, default=False)
    process_analysis = Column(Text, nullable=True)
    content_analysis = Column(Text, nullable=True)
    structure_analysis = Column(Text, nullable=True)
    language_analysis = Column(Text, nullable=True)
    mistakes = Column(JSON, nullable=False, default=list)
    errors = Column(JSON, nullable=False, default=list)
    strengths = Column(JSON, nullable=False, default=list)
    knowledge_points = Column(JSON, nullable=False, default=list)
    weak_points = Column(JSON, nullable=False, default=list)
    dimension_scores = Column(JSON, nullable=False, default=dict)
    correct_solution = Column(Text, nullable=True)
    revised_example = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)
    review_note = Column(Text, nullable=True)
    ai_engine = Column(String(120), nullable=True)
    ai_metadata = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submission = relationship("Submission", back_populates="grading_result")


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(20), nullable=False, index=True)
    name = Column(String(80), nullable=False, index=True)
    description = Column(Text, nullable=True)


class TeacherAnnotation(Base):
    __tablename__ = "teacher_annotations"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    label = Column(String(80), nullable=False)
    comment = Column(Text, nullable=True)
    corrected_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("Submission", back_populates="annotations")
    teacher = relationship("User")
