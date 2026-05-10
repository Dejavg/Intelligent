from __future__ import annotations

from dataclasses import dataclass

from ..models import Assignment
from .grading import GradingService


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    ocr_text: str
    expected_score: float
    expected_full_score: float
    expected_wrong_questions: list[str]
    tolerance: float = 8


class EvaluationService:
    """Small deterministic benchmark for grading accuracy demonstrations."""

    def __init__(self, grading_service: GradingService | None = None) -> None:
        self.grading_service = grading_service or GradingService()

    def run_grading_benchmark(self) -> dict:
        assignment = Assignment(
            title="AI 自动识别整张答题卡评测",
            subject="自动识别",
            question_type="答题卡",
            question="整张答题卡",
            standard_answer="",
            full_score=100,
            knowledge_points=["整张答题卡", "数学过程批改"],
        )
        case_results = []
        for case in _benchmark_cases():
            result = self.grading_service._grade_answer_sheet_from_text(
                case.ocr_text,
                assignment,
                ["评测模式：使用标准 OCR 文本直接测试批改模块。"],
            )
            predicted_wrong = _wrong_question_numbers(result or {})
            actual_score = float((result or {}).get("score", 0))
            score_error = abs(actual_score - case.expected_score)
            wrong_match = set(predicted_wrong) == set(case.expected_wrong_questions)
            score_pass = score_error <= case.tolerance
            case_results.append(
                {
                    "name": case.name,
                    "expected_score": case.expected_score,
                    "actual_score": actual_score,
                    "expected_full_score": case.expected_full_score,
                    "actual_full_score": float((result or {}).get("full_score", 0)),
                    "score_error": round(score_error, 2),
                    "score_pass": score_pass,
                    "expected_wrong_questions": case.expected_wrong_questions,
                    "predicted_wrong_questions": predicted_wrong,
                    "wrong_question_match": wrong_match,
                    "passed": bool(result) and score_pass and wrong_match,
                }
            )

        total = len(case_results)
        passed = sum(1 for item in case_results if item["passed"])
        return {
            "summary": {
                "total_cases": total,
                "passed_cases": passed,
                "pass_rate": round(passed / total, 4) if total else 0,
                "score_within_tolerance_rate": round(
                    sum(1 for item in case_results if item["score_pass"]) / total,
                    4,
                )
                if total
                else 0,
                "wrong_question_accuracy": round(
                    sum(1 for item in case_results if item["wrong_question_match"]) / total,
                    4,
                )
                if total
                else 0,
                "average_score_error": round(
                    sum(float(item["score_error"]) for item in case_results) / total,
                    2,
                )
                if total
                else 0,
            },
            "cases": case_results,
            "rubric": "内置评测集覆盖全对、计算错误、方程末步错误和应用题数量关系，主要用于比赛 Demo 的可解释准确率展示。",
        }


def _wrong_question_numbers(result: dict) -> list[str]:
    questions = (((result.get("ai_metadata") or {}).get("answer_sheet") or {}).get("questions") or [])
    wrong = []
    for index, question in enumerate(questions, start=1):
        if isinstance(question, dict) and not question.get("is_correct"):
            wrong.append(str(question.get("question_no") or index))
    return wrong


def _benchmark_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            name="五题数学卷：两题计算/方程错误",
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
            name="三题数学卷：全部正确",
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
            name="方程题：最后一步除法错误",
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
    ]
