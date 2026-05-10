import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal, UPLOAD_DIR, init_db
from backend.app.main import app
from backend.app.models import Assignment, ClassRoom, Submission
from backend.app.services.llm import normalize_answer_sheet_grading


def cleanup_demo_rows():
    init_db()
    with SessionLocal() as db:
        db.query(Assignment).filter(Assignment.title == "自动化测试题").delete()
        db.query(ClassRoom).filter(ClassRoom.name == "自动化测试班").delete()
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-bulk.png").all():
            db.delete(submission)
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-demo-paper.png").all():
            db.delete(submission)
        db.commit()


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        cleanup_demo_rows()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        cleanup_demo_rows()

    def test_core_demo_flow(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertTrue(self.client.get("/api/students").json()["data"])

        assignment_id = self.client.get("/api/assignments").json()["data"][0]["id"]
        upload = self.client.post(
            "/api/upload",
            json={
                "student_id": 1,
                "assignment_id": assignment_id,
                "subject": "数学",
                "question_type": "计算题",
                "image_name": "pytest-bulk.png",
                "image_data": "",
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]
        self.assertEqual(self.client.post("/api/ocr", json={"submission_id": submission_id}).status_code, 200)
        grade = self.client.post("/api/grade", json={"submission_id": submission_id})
        self.assertEqual(grade.status_code, 200)
        self.assertIsNotNone(grade.json()["data"]["submission"]["ai_score"])

        annotation = self.client.post(
            f"/api/submissions/{submission_id}/annotations",
            json={"label": "AI 评分偏高", "comment": "保留为教师二次标注样例", "corrected_score": 9},
        )
        self.assertEqual(annotation.status_code, 200)

    def test_management_endpoints(self):
        question = self.client.post(
            "/api/question-bank",
            json={
                "title": "自动化测试题",
                "subject": "数学",
                "question_type": "计算题",
                "question": "解方程 x + 1 = 3",
                "standard_answer": "x = 2",
                "full_score": 10,
                "knowledge_points": ["一元一次方程"],
            },
        )
        self.assertEqual(question.status_code, 200)

        classroom = self.client.post(
            "/api/classes",
            json={"name": "自动化测试班", "grade": "七年级", "teacher_name": "陈老师"},
        )
        self.assertEqual(classroom.status_code, 200)

        bulk = self.client.post(
            "/api/bulk-upload",
            json={
                "auto_ocr": True,
                "auto_grade": True,
                "items": [{"student_id": 1, "assignment_id": question.json()["data"]["id"], "image_name": "pytest-bulk.png"}],
            },
        )
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(bulk.json()["data"]["count"], 1)

        reset = self.client.post("/api/demo/reset")
        self.assertEqual(reset.status_code, 200)
        self.assertGreaterEqual(reset.json()["data"]["restored_demo_submissions"], 1)

    def test_answer_sheet_normalization(self):
        raw = {
            "score": 15,
            "full_score": 20,
            "summary": "整张答题卡包含两道题。",
            "comment": "整体表现不错，但第二题需要订正。",
            "suggestion": "复习移项和过去时。",
            "common_weak_points": ["移项", "一般过去时"],
            "questions": [
                {
                    "question_no": "1",
                    "subject": "数学",
                    "question_type": "计算题",
                    "question_text": "解方程 2x+3=7",
                    "student_answer": "x=2",
                    "score": 10,
                    "full_score": 10,
                    "is_correct": True,
                    "knowledge_points": ["一元一次方程"],
                },
                {
                    "question_no": "2",
                    "subject": "英语",
                    "question_type": "作文",
                    "student_answer": "I go to park.",
                    "score": 5,
                    "full_score": 10,
                    "mistakes": [{"step": "I go", "error": "过去经历应使用过去时。"}],
                    "weak_points": ["一般过去时"],
                },
            ],
        }
        result = normalize_answer_sheet_grading(raw, "kimi", "kimi-k2.5")
        self.assertEqual(result["score"], 15)
        self.assertEqual(result["full_score"], 20)
        self.assertEqual(len(result["ai_metadata"]["answer_sheet"]["questions"]), 2)
        self.assertIn("一般过去时", result["weak_points"])

    def test_answer_sheet_grading_failure_keeps_ocr_context(self):
        from backend.app.services.grading import GradingService

        assignment = Assignment(
            title="AI 自动识别整张答题卡",
            subject="自动识别",
            question_type="答题卡",
            question="整张答题卡",
            standard_answer="",
            full_score=100,
            knowledge_points=["整张答题卡"],
        )
        service = GradingService()
        result = service._grading_failed_result(assignment, "1. 2x+3=7\n答：x=2", ["The read operation timed out"])
        self.assertEqual(result["ai_engine"], "LLMGradingFailed")
        self.assertIn("OCR 已识别", result["process_analysis"])
        self.assertNotIn("未能从上传图片中识别", result["process_analysis"])

    def test_answer_sheet_text_fallback_grades_math_sheet(self):
        from backend.app.services.grading import GradingService

        assignment = Assignment(
            title="AI 自动识别整张答题卡",
            subject="自动识别",
            question_type="答题卡",
            question="整张答题卡",
            standard_answer="",
            full_score=100,
            knowledge_points=["整张答题卡"],
        )
        ocr_text = """数学练习卷
1. 计算：36÷4+5×2
36÷4=9
5×2=10
9+10=19
答：19

2. 解方程：2x+3=11
2x=11-3
2x=8
x=4
答：x=4

3. 计算：15×6-28
15×6=90
90-28=72
答：72

4. 解方程：3x-5=10
3x=10+5
3x=15
x=4
答：x=4

5. 应用题：小明买了3支铅笔，每支2元，又买了1本笔记本5元，一共用了多少钱？
3×2=6（元）
6+5=11（元）
答：一共用了11元。
"""
        result = GradingService()._grade_answer_sheet_from_text(ocr_text, assignment, ["The read operation timed out"])
        self.assertIsNotNone(result)
        self.assertEqual(result["ai_engine"], "LocalFallback:OCRRule")
        self.assertEqual(result["full_score"], 100)
        self.assertLess(result["score"], 100)
        self.assertGreater(result["score"], 80)
        questions = result["ai_metadata"]["answer_sheet"]["questions"]
        self.assertEqual(len(questions), 5)
        self.assertFalse(questions[3]["is_correct"])
        self.assertIn("方程求解", result["weak_points"])

    def test_grading_evaluation_endpoint(self):
        response = self.client.get("/api/evaluation/grading")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertGreaterEqual(data["summary"]["total_cases"], 10)
        self.assertGreaterEqual(data["summary"]["wrong_question_accuracy"], 0.6)
        self.assertTrue(data["cases"])

    def test_fixed_demo_math_paper_flow(self):
        assignments = self.client.get("/api/assignments").json()["data"]
        assignment = next(item for item in assignments if item["subject"] == "自动识别")
        upload = self.client.post(
            "/api/upload",
            json={
                "student_id": 1,
                "assignment_id": assignment["id"],
                "subject": "自动识别",
                "question_type": "答题卡",
                "image_name": "pytest-demo-paper.png",
                "image_data": "data:image/png;base64,iVBORw0KGgo=",
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]

        ocr = self.client.post("/api/ocr", json={"submission_id": submission_id})
        self.assertEqual(ocr.status_code, 200)
        self.assertEqual(ocr.json()["data"]["ocr"]["engine"], "DemoMathPaperOCR")
        self.assertEqual(len(ocr.json()["data"]["ocr"]["blocks"]) - 1, 5)

        grade = self.client.post("/api/grade", json={"submission_id": submission_id})
        self.assertEqual(grade.status_code, 200)
        result = grade.json()["data"]["grading_result"]
        self.assertEqual(result["ai_engine"], "DemoRule:FixedMathPaper")
        self.assertEqual(result["score"], 43)
        self.assertEqual(result["full_score"], 50)
        questions = result["ai_metadata"]["answer_sheet"]["questions"]
        self.assertEqual(len(questions), 5)
        self.assertEqual(questions[2]["score"], 6)
        self.assertEqual(questions[2]["status"], "wrong")
        self.assertIn("62", questions[2]["correct_solution"])
        self.assertNotIn("72；答", questions[2]["correct_solution"])
        self.assertEqual(questions[3]["score"], 7)
        self.assertEqual(questions[3]["status"], "partial")

    def test_image_preprocess_creates_enhanced_copy(self):
        try:
            from PIL import Image, ImageDraw  # type: ignore
        except ImportError:
            self.skipTest("Pillow is not installed")

        from backend.app.services.ocr import _prepare_image_for_ocr

        image_path = UPLOAD_DIR / "pytest-preprocess.png"
        image = Image.new("RGB", (900, 520), "white")
        draw = ImageDraw.Draw(image)
        draw.text((60, 80), "1. 2x + 3 = 11", fill="black")
        draw.text((60, 130), "2x = 8", fill="black")
        draw.text((60, 180), "x = 4", fill="black")
        image.save(image_path)

        submission = Submission(id=999, image_url="/uploads/pytest-preprocess.png", image_name="pytest-preprocess.png")
        result = _prepare_image_for_ocr(image_path, submission)
        try:
            self.assertTrue(result.metadata["enabled"])
            self.assertTrue(result.path.exists())
            self.assertIn("operations", result.metadata)
        finally:
            image_path.unlink(missing_ok=True)
            if result.path != image_path:
                Path(result.path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
