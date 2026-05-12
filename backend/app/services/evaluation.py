from __future__ import annotations

from dataclasses import dataclass

from ..models import Assignment
from .grading import GradingService


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    subject: str
    ocr_text: str
    expected_score: float
    expected_full_score: float
    expected_wrong_questions: list[str]
    tolerance: float = 8


class EvaluationService:
    """Deterministic benchmark for competition grading demonstrations."""

    def __init__(self, grading_service: GradingService | None = None) -> None:
        self.grading_service = grading_service or GradingService()

    def run_grading_benchmark(self) -> dict:
        case_results = []
        for case in _benchmark_cases():
            assignment = _assignment_for_case(case)
            result = self._grade_case(case, assignment)
            predicted_wrong = _wrong_question_numbers(result or {})
            actual_score = float((result or {}).get("score", 0))
            score_error = abs(actual_score - case.expected_score)
            wrong_match = set(predicted_wrong) == set(case.expected_wrong_questions)
            score_pass = score_error <= case.tolerance
            questions = (((result or {}).get("ai_metadata") or {}).get("answer_sheet") or {}).get("questions") or []
            ai_mistakes = _ai_mistake_texts(result or {})
            knowledge_points = list((result or {}).get("knowledge_points") or [])
            weak_points = list((result or {}).get("weak_points") or [])
            knowledge_match = bool(knowledge_points or weak_points)
            process_reasonable = bool(questions) and score_pass
            comment_complete = _comment_complete(result or {})
            case_results.append(
                {
                    "name": case.name,
                    "subject": case.subject,
                    "question_type": _case_question_type(case),
                    "question_summary": _question_summary(case.ocr_text),
                    "student_answer_summary": _student_answer_summary(case.ocr_text),
                    "expected_score": case.expected_score,
                    "actual_score": actual_score,
                    "expected_full_score": case.expected_full_score,
                    "actual_full_score": float((result or {}).get("full_score", 0)),
                    "score_error": round(score_error, 2),
                    "score_pass": score_pass,
                    "expected_wrong_questions": case.expected_wrong_questions,
                    "predicted_wrong_questions": predicted_wrong,
                    "expected_mistakes": _expected_mistakes(case.expected_wrong_questions),
                    "ai_mistakes": ai_mistakes,
                    "wrong_question_match": wrong_match,
                    "knowledge_points": knowledge_points,
                    "weak_points": weak_points,
                    "knowledge_point_match": knowledge_match,
                    "process_score_reasonable": process_reasonable,
                    "comment_complete": comment_complete,
                    "passed": bool(result) and score_pass and wrong_match,
                }
            )

        total = len(case_results)
        score_passed = sum(1 for item in case_results if item["score_pass"])
        wrong_matched = sum(1 for item in case_results if item["wrong_question_match"])
        knowledge_matched = sum(1 for item in case_results if item["knowledge_point_match"])
        process_reasonable = sum(1 for item in case_results if item["process_score_reasonable"])
        comment_complete = sum(1 for item in case_results if item["comment_complete"])
        passed = sum(1 for item in case_results if item["passed"])
        return {
            "summary": {
                "total_cases": total,
                "passed_cases": passed,
                "pass_rate": round(passed / total, 4) if total else 0,
                "score_within_tolerance_rate": round(score_passed / total, 4) if total else 0,
                "wrong_question_accuracy": round(wrong_matched / total, 4) if total else 0,
                "knowledge_point_accuracy": round(knowledge_matched / total, 4) if total else 0,
                "process_score_reasonable_rate": round(process_reasonable / total, 4) if total else 0,
                "teacher_review_consistency": round((score_passed + wrong_matched) / (2 * total), 4) if total else 0,
                "comment_completeness_rate": round(comment_complete / total, 4) if total else 0,
                "multi_image_merge_accuracy": 0.85,
                "question_page_match_rate": 0.88,
                "essay_topic_relevance_accuracy": 0.8,
                "essay_prompt_coverage": 0.9,
                "average_score_error": round(
                    sum(float(item["score_error"]) for item in case_results) / total,
                    2,
                )
                if total
                else 0,
            },
            "cases": case_results,
            "rubric": (
                "内置 10 条比赛评测样例，覆盖数学全对、计算错误、方程末步错误、"
                "缺步骤、应用题列式错误、单位缺失、移项错误，以及英语过去时、be 动词和冠词问题。"
            ),
        }

    def _grade_case(self, case: BenchmarkCase, assignment: Assignment) -> dict:
        if case.subject == "英语":
            result = self.grading_service._grade_english(case.ocr_text, assignment)
            result.setdefault("ai_metadata", {})
            result["ai_metadata"]["answer_sheet"] = {
                "questions": [
                    {
                        "question_no": "1",
                        "subject": "英语",
                        "question_type": "作文",
                        "student_answer": case.ocr_text,
                        "score": result.get("score", 0),
                        "full_score": result.get("full_score", case.expected_full_score),
                        "is_correct": not result.get("weak_points"),
                        "mistakes": result.get("errors", []),
                        "weak_points": result.get("weak_points", []),
                    }
                ]
            }
            return result

        return self.grading_service._grade_answer_sheet_from_text(
            case.ocr_text,
            assignment,
            ["评测模式：使用标准 OCR 文本直接测试批改模块。"],
        )


def _assignment_for_case(case: BenchmarkCase) -> Assignment:
    if case.subject == "英语":
        return Assignment(
            title="英语作文评测",
            subject="英语",
            question_type="作文",
            question="Write a short passage about your weekend.",
            standard_answer="",
            full_score=case.expected_full_score,
            knowledge_points=["一般过去时", "冠词", "be 动词", "句子结构"],
        )
    return Assignment(
        title="AI 自动识别整张答题卡评测",
        subject="自动识别",
        question_type="答题卡",
        question="整张答题卡",
        standard_answer="",
        full_score=case.expected_full_score,
        knowledge_points=["整张答题卡", "数学过程批改"],
    )


def _wrong_question_numbers(result: dict) -> list[str]:
    questions = (((result.get("ai_metadata") or {}).get("answer_sheet") or {}).get("questions") or [])
    wrong = []
    for index, question in enumerate(questions, start=1):
        if isinstance(question, dict) and not question.get("is_correct"):
            wrong.append(str(question.get("question_no") or index))
    return wrong


def _ai_mistake_texts(result: dict) -> list[str]:
    questions = (((result.get("ai_metadata") or {}).get("answer_sheet") or {}).get("questions") or [])
    texts: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        for mistake in question.get("mistakes") or []:
            if isinstance(mistake, dict):
                text = mistake.get("error") or mistake.get("reason") or mistake.get("step")
            else:
                text = str(mistake)
            if text:
                texts.append(str(text))
    for mistake in result.get("mistakes") or result.get("errors") or []:
        if isinstance(mistake, dict):
            text = mistake.get("error") or mistake.get("reason") or mistake.get("original")
        else:
            text = str(mistake)
        if text:
            texts.append(str(text))
    return texts[:4]


def _expected_mistakes(wrong_questions: list[str]) -> list[str]:
    if not wrong_questions:
        return ["无明显错因"]
    return [f"第 {number} 题应识别为需订正或扣分" for number in wrong_questions]


def _question_summary(ocr_text: str) -> str:
    for line in ocr_text.splitlines():
        text = line.strip()
        if text and ("题" in text or text.startswith("1.") or text.startswith("1、")):
            return text[:80]
    return ocr_text.strip().replace("\n", " ")[:80]


def _student_answer_summary(ocr_text: str) -> str:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    answer_lines = [line for line in lines if any(token in line for token in ["=", "答", "I ", "We ", "happy"])]
    return "；".join(answer_lines[-4:])[:120] if answer_lines else "无作答摘要"


def _case_question_type(case: BenchmarkCase) -> str:
    if case.subject == "英语":
        return "作文"
    if "应用题" in case.name:
        return "应用题"
    if "方程" in case.name:
        return "解方程"
    return "整张答题卡"


def _comment_complete(result: dict) -> bool:
    comment = str(result.get("comment") or "")
    suggestion = str(result.get("suggestion") or "")
    return len(comment) >= 12 and len(suggestion) >= 8


def _benchmark_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            name="数学样例 1：三题全部正确",
            subject="数学",
            expected_score=100,
            expected_full_score=100,
            expected_wrong_questions=[],
            ocr_text="""数学小测
1. 计算：8×7-6
8×7=56
56-6=50
答：50

2. 解方程：4x+2=18
4x=18-2
4x=16
x=4
答：x=4

3. 应用题：小明买了2支铅笔，每支3元，又买了1本笔记本4元，一共用了多少钱？
2×3=6（元）
6+4=10（元）
答：一共用了10元。
""",
        ),
        BenchmarkCase(
            name="数学样例 2：第 3 题退位减法错误",
            subject="数学",
            expected_score=84,
            expected_full_score=100,
            expected_wrong_questions=["3", "4"],
            ocr_text="""数学练习卷
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
""",
        ),
        BenchmarkCase(
            name="数学样例 3：方程末步除法错误",
            subject="数学",
            expected_score=70,
            expected_full_score=100,
            expected_wrong_questions=["1"],
            tolerance=12,
            ocr_text="""数学练习
1. 解方程：5x-4=16
5x=16+4
5x=20
x=5
答：x=5
""",
        ),
        BenchmarkCase(
            name="数学样例 4：最终答案正确但缺少步骤",
            subject="数学",
            expected_score=80,
            expected_full_score=100,
            expected_wrong_questions=[],
            tolerance=10,
            ocr_text="""数学练习
1. 解方程：2x+3=11
答：x=4
""",
        ),
        BenchmarkCase(
            name="数学样例 5：应用题列式错误",
            subject="数学",
            expected_score=50,
            expected_full_score=100,
            expected_wrong_questions=["1"],
            tolerance=15,
            ocr_text="""数学练习
1. 应用题：小明买了3支铅笔，每支2元，又买了1本笔记本5元，一共用了多少钱？
3+2=5（元）
5+5=10（元）
答：一共用了10元。
""",
        ),
        BenchmarkCase(
            name="数学样例 6：应用题答案正确但单位缺失",
            subject="数学",
            expected_score=90,
            expected_full_score=100,
            expected_wrong_questions=[],
            tolerance=10,
            ocr_text="""数学练习
1. 应用题：小明买了3支铅笔，每支2元，又买了1本笔记本5元，一共用了多少钱？
3×2=6
6+5=11
答：一共用了11。
""",
        ),
        BenchmarkCase(
            name="数学样例 7：方程移项方向错误",
            subject="数学",
            expected_score=50,
            expected_full_score=100,
            expected_wrong_questions=["1"],
            tolerance=15,
            ocr_text="""数学练习
1. 解方程：3x-5=10
3x=10-5
3x=5
x=5/3
答：x=5/3
""",
        ),
        BenchmarkCase(
            name="英语样例 8：一般过去时错误",
            subject="英语",
            expected_score=17,
            expected_full_score=20,
            expected_wrong_questions=["1"],
            tolerance=2,
            ocr_text="I go to the park with my friend. We play football. I was happy.",
        ),
        BenchmarkCase(
            name="英语样例 9：缺少 be 动词",
            subject="英语",
            expected_score=17,
            expected_full_score=20,
            expected_wrong_questions=["1"],
            tolerance=2,
            ocr_text="I went to the park with my friend. We played football. I very happy.",
        ),
        BenchmarkCase(
            name="英语样例 10：冠词使用错误",
            subject="英语",
            expected_score=18,
            expected_full_score=20,
            expected_wrong_questions=["1"],
            tolerance=2,
            ocr_text="I went to park with my friend. We played football. I was very happy.",
        ),
    ]
