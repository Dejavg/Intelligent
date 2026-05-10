import unittest

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal, init_db
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


if __name__ == "__main__":
    unittest.main()
