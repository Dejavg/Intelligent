import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal, UPLOAD_DIR, init_db
from backend.app.main import app
from backend.app.models import Assignment, ClassRoom, Submission
from backend.app.services.llm import normalize_answer_sheet_grading
from backend.app.settings import settings


VALID_1X1_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"


def cleanup_demo_rows():
    init_db()
    with SessionLocal() as db:
        db.query(Assignment).filter(Assignment.title == "pytest-objective-choice").delete()
        db.query(Assignment).filter(Assignment.title == "自动化测试题").delete()
        db.query(ClassRoom).filter(ClassRoom.name == "自动化测试班").delete()
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-bulk.png").all():
            db.delete(submission)
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-demo-paper.png").all():
            db.delete(submission)
        for submission in db.query(Submission).filter(Submission.batch_id.like("batch_%")).all():
            if submission.image_name and submission.image_name.startswith("pytest-batch"):
                db.delete(submission)
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-essay.png").all():
            db.delete(submission)
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-chinese-essay.png").all():
            db.delete(submission)
        for submission in db.query(Submission).filter(Submission.image_name == "pytest-objective.png").all():
            db.delete(submission)
        db.commit()


class ApiFlowTest(unittest.TestCase):
    def setUp(self):
        self._demo_fixed_math_paper_ocr = settings.demo_fixed_math_paper_ocr
        object.__setattr__(settings, "demo_fixed_math_paper_ocr", True)
        cleanup_demo_rows()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        object.__setattr__(settings, "demo_fixed_math_paper_ocr", self._demo_fixed_math_paper_ocr)
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
                "image_data": VALID_1X1_PNG,
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

        reset = self.client.post("/api/demo/reset", json={"confirm": "RESET_DEMO_DATA"})
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
                "image_data": VALID_1X1_PNG,
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

    def test_quick_demo_can_force_fixed_ocr_in_real_mode(self):
        object.__setattr__(settings, "demo_fixed_math_paper_ocr", False)
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
                "image_data": VALID_1X1_PNG,
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]

        ocr = self.client.post(
            "/api/ocr",
            json={"submission_id": submission_id, "force_demo_fixed_math_paper": True},
        )
        self.assertEqual(ocr.status_code, 200)
        self.assertEqual(ocr.json()["data"]["ocr"]["engine"], "DemoMathPaperOCR")

        grade = self.client.post("/api/grade", json={"submission_id": submission_id})
        self.assertEqual(grade.status_code, 200)
        result = grade.json()["data"]["grading_result"]
        self.assertEqual(result["ai_engine"], "DemoRule:FixedMathPaper")
        self.assertEqual(result["score"], 43)

    def test_batch_upload_ocr_and_grade_flow(self):
        assignments = self.client.get("/api/assignments").json()["data"]
        assignment = next(item for item in assignments if item["subject"] == "自动识别")
        upload = self.client.post(
            "/api/upload/batch",
            json={
                "student_id": 1,
                "assignment_id": assignment["id"],
                "subject": "自动识别",
                "question_type": "答题卡",
                "images": [
                    {"page_index": 1, "image_name": "pytest-batch-page-1.png", "image_data": VALID_1X1_PNG},
                    {"page_index": 2, "image_name": "pytest-batch-page-2.png", "image_data": VALID_1X1_PNG},
                ],
            },
        )
        self.assertEqual(upload.status_code, 200)
        payload = upload.json()["data"]
        self.assertEqual(len(payload["pages"]), 2)

        ocr = self.client.post(
            "/api/ocr/batch",
            json={
                "submission_id": payload["submission_id"],
                "batch_id": payload["batch_id"],
                "subject": "自动识别",
                "question_type": "答题卡",
                "pages": payload["pages"],
            },
        )
        self.assertEqual(ocr.status_code, 200)
        ocr_data = ocr.json()["data"]
        self.assertEqual(ocr_data["merge_summary"]["question_count"], 5)
        self.assertEqual(ocr_data["questions"][2]["student_answer"].splitlines()[-1], "答：72")

        grade = self.client.post(
            "/api/grade/batch",
            json={
                "submission_id": payload["submission_id"],
                "batch_id": payload["batch_id"],
                "student_id": 1,
                "subject": "自动识别",
                "question_type": "答题卡",
                "merged_ocr_text": ocr_data["merged_ocr_text"],
                "questions": ocr_data["questions"],
                "page_results": ocr_data["page_results"],
            },
        )
        self.assertEqual(grade.status_code, 200)
        result = grade.json()["data"]["grading_result"]
        self.assertEqual(result["score"], 43)
        self.assertEqual(result["full_score"], 50)
        self.assertEqual(result["ai_metadata"]["batch_merge"]["page_count"], 2)

    def test_essay_prompt_is_stored_and_used(self):
        assignments = self.client.get("/api/assignments").json()["data"]
        assignment = next(item for item in assignments if item["subject"] == "英语")
        essay_prompt = "Write a short passage about your weekend. You should write at least 60 words."
        upload = self.client.post(
            "/api/upload",
            json={
                "student_id": 3,
                "assignment_id": assignment["id"],
                "subject": "英语",
                "question_type": "作文",
                "image_name": "pytest-essay.png",
                "image_data": VALID_1X1_PNG,
                "essay_prompt": essay_prompt,
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]
        grade = self.client.post(
            "/api/grade",
            json={
                "submission_id": submission_id,
                "subject": "英语",
                "question_type": "作文",
                "ocr_text": "I go to park with my friend. We play football. I very happy.",
                "essay_prompt": essay_prompt,
            },
        )
        self.assertEqual(grade.status_code, 200)
        detail = self.client.get(f"/api/submissions/{submission_id}").json()["data"]
        self.assertEqual(detail["essay_prompt"], essay_prompt)
        self.assertEqual(detail["grading_result"]["ai_metadata"]["essay_prompt"], essay_prompt)

    def test_chinese_composition_type_is_available_and_gradable(self):
        assignments = self.client.get("/api/assignments").json()["data"]
        assignment = next(
            (item for item in assignments if item["subject"] == "语文" and item["question_type"] == "作文"),
            None,
        )
        self.assertIsNotNone(assignment)

        essay_prompt = "请以《难忘的一天》为题写一篇不少于 600 字的作文。"
        upload = self.client.post(
            "/api/upload",
            json={
                "student_id": 3,
                "subject": "语文",
                "question_type": "作文",
                "image_name": "pytest-chinese-essay.png",
                "image_data": VALID_1X1_PNG,
                "essay_prompt": essay_prompt,
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]

        grade = self.client.post(
            "/api/grade",
            json={
                "submission_id": submission_id,
                "subject": "语文",
                "question_type": "作文",
                "ocr_text": "今天学校举行运动会。接力赛时同学们一直为我加油，我感到集体的力量非常温暖。",
                "essay_prompt": essay_prompt,
            },
        )
        self.assertEqual(grade.status_code, 200)
        data = grade.json()["data"]
        result = data["grading_result"]
        self.assertEqual(data["submission"]["subject"], "语文")
        self.assertEqual(data["submission"]["question_type"], "作文")
        self.assertEqual(result["full_score"], 60)
        self.assertIn("composition_dimensions", result["ai_metadata"])

    def test_objective_choice_grading_and_report_fields(self):
        question = self.client.post(
            "/api/question-bank",
            json={
                "title": "pytest-objective-choice",
                "subject": "数学",
                "question_type": "选择题",
                "question": "选择题：下列结果正确的是哪一项？A. 1 B. 2 C. 3 D. 4",
                "standard_answer": "B",
                "full_score": 5,
                "knowledge_points": ["选择题审题"],
            },
        )
        self.assertEqual(question.status_code, 200)
        assignment_id = question.json()["data"]["id"]
        upload = self.client.post(
            "/api/upload",
            json={
                "student_id": 1,
                "assignment_id": assignment_id,
                "subject": "数学",
                "question_type": "选择题",
                "image_name": "pytest-objective.png",
                "image_data": VALID_1X1_PNG,
            },
        )
        self.assertEqual(upload.status_code, 200)
        submission_id = upload.json()["data"]["submission_id"]
        grade = self.client.post(
            "/api/grade",
            json={"submission_id": submission_id, "subject": "数学", "question_type": "选择题", "ocr_text": "答案：B"},
        )
        self.assertEqual(grade.status_code, 200)
        result = grade.json()["data"]["grading_result"]
        self.assertEqual(result["score"], 5)
        self.assertTrue(result["is_correct"])
        self.assertTrue(result["ai_metadata"]["objective_grading"])

        report = self.client.get("/api/students/1/report")
        self.assertEqual(report.status_code, 200)
        report_data = report.json()["data"]
        self.assertIn("score_trend", report_data)
        self.assertIn("knowledge_mastery", report_data)
        self.assertIn("error_distribution", report_data)

        analysis = self.client.get("/api/classes/%E4%B8%83%E5%B9%B4%E7%BA%A7%E4%B8%80%E7%8F%AD/analysis")
        self.assertEqual(analysis.status_code, 200)
        analysis_data = analysis.json()["data"]
        self.assertIn("layer_analysis", analysis_data)
        self.assertIn("student_comparison", analysis_data)
        self.assertEqual([item["subject"] for item in analysis_data["subject_analysis"]], ["数学", "英语", "语文"])
        self.assertTrue(all("score_rate" in item for item in analysis_data["subject_analysis"]))

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
