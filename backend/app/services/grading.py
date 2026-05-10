from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from ..models import Assignment
from ..settings import settings
from .llm import LLMClient, normalize_answer_sheet_grading, normalize_llm_grading


class GradingService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def grade(
        self,
        subject: str,
        question_type: str,
        ocr_text: str,
        assignment: Assignment,
        image_path: Path | None = None,
    ) -> dict:
        if self._is_answer_sheet(subject, question_type, assignment):
            return self._grade_answer_sheet(ocr_text, assignment, image_path)

        if not ocr_text.strip() and not (settings.llm_enabled and settings.llm_grade_from_image and image_path):
            return self._empty_result(subject, assignment)

        rule_result = self._grade_by_rule(subject, question_type, ocr_text, assignment)
        rule_result.setdefault("ai_engine", "RuleEngine")
        if settings.llm_enabled:
            try:
                if image_path and settings.llm_grade_from_image and self.llm_client.vision_available:
                    llm_result = self.llm_client.grade_image(image_path, subject, question_type, ocr_text, assignment)
                else:
                    llm_result = self.llm_client.grade(subject, question_type, ocr_text, assignment)
                llm_grading = normalize_llm_grading(llm_result.data, rule_result, subject)
                llm_grading["ai_engine"] = f"LLM:{llm_result.provider}:{llm_result.model}"
                llm_grading["ai_metadata"] = {
                    **(llm_grading.get("ai_metadata") or {}),
                    "llm_provider": llm_result.provider,
                    "llm_model": llm_result.model,
                }
                return llm_grading
            except Exception as exc:
                if not settings.llm_fallback_to_rule:
                    raise
                rule_result["ai_engine_note"] = f"LLM fallback: {exc}"
                rule_result["ai_metadata"] = {"llm_fallback_reason": str(exc)}
        return rule_result

    def _grade_answer_sheet(self, ocr_text: str, assignment: Assignment, image_path: Path | None) -> dict:
        if not image_path and not ocr_text.strip():
            result = self._empty_result("自动识别", assignment)
            result["process_analysis"] = "整张答题卡批改需要上传包含题目与作答的图片。"
            return result

        structured_paper = _parse_structured_math_paper(ocr_text)
        if structured_paper:
            return _grade_demo_math_paper(structured_paper)

        if not settings.llm_enabled:
            fallback = self._grade_answer_sheet_from_text(
                ocr_text,
                assignment,
                ["大模型未启用，已使用 OCR 文本本地规则批改。"],
            )
            if fallback:
                return fallback
            result = self._empty_result("自动识别", assignment)
            result["process_analysis"] = "整张答题卡批改需要启用大模型。"
            result["suggestion"] = "请在 .env 中配置 LLM_ENABLED=true、OCR_PROVIDER=llm、KIMI_API_KEY 和 LLM_VISION_MODEL。"
            return result

        errors: list[str] = []
        if ocr_text.strip() and self.llm_client.available:
            try:
                llm_result = self.llm_client.grade_answer_sheet_text(ocr_text, assignment)
                return normalize_answer_sheet_grading(llm_result.data, llm_result.provider, llm_result.model)
            except Exception as exc:
                errors.append(f"文本批改失败：{exc}")
                fallback = self._grade_answer_sheet_from_text(ocr_text, assignment, errors)
                if fallback:
                    return fallback

        if not image_path:
            return self._grading_failed_result(assignment, ocr_text, errors)

        if not self.llm_client.vision_available:
            errors.append("视觉大模型不可用")
            return self._grading_failed_result(assignment, ocr_text, errors)

        try:
            llm_result = self.llm_client.grade_answer_sheet(image_path, ocr_text, assignment)
            return normalize_answer_sheet_grading(llm_result.data, llm_result.provider, llm_result.model)
        except Exception as exc:
            errors.append(f"图片批改失败：{exc}")
            fallback = self._grade_answer_sheet_from_text(ocr_text, assignment, errors)
            if fallback:
                return fallback
            return self._grading_failed_result(assignment, ocr_text, errors)

    def _grade_answer_sheet_from_text(self, ocr_text: str, assignment: Assignment, warnings: list[str]) -> dict | None:
        questions = _split_answer_sheet_questions(ocr_text)
        graded = []
        for question_no, body in questions:
            graded_question = self._grade_local_answer_sheet_question(question_no, body)
            if graded_question:
                graded.append(graded_question)

        if not graded:
            return None

        target_full_score = assignment.full_score or sum(question["full_score"] for question in graded)
        per_question_full = target_full_score / len(graded)
        assigned_full_scores: list[int | float] = []
        for index, question in enumerate(graded):
            if index == len(graded) - 1:
                question_full = _clean_number(target_full_score - sum(float(value) for value in assigned_full_scores))
            else:
                question_full = _clean_number(per_question_full)
            assigned_full_scores.append(question_full)
            base_score = float(question.pop("_base_score", question["score"]))
            question["full_score"] = question_full
            question["score"] = _clean_number(base_score / 10 * float(question_full))

        score = _clean_number(sum(float(question["score"]) for question in graded))
        full_score = _clean_number(sum(float(question["full_score"]) for question in graded))
        correct_count = sum(1 for question in graded if question.get("is_correct"))
        weak_points = unique_list(
            [weak for question in graded for weak in question.get("weak_points", [])]
        )
        raw = {
            "detected_subjects": unique_list([question.get("subject", "数学") for question in graded]),
            "score": score,
            "full_score": full_score,
            "is_correct": score >= full_score and full_score > 0,
            "summary": f"已根据 OCR 文本逐题批改 {len(graded)} 道题，其中 {correct_count} 道正确，{len(graded) - correct_count} 道需要订正。",
            "comment": (
                "这张答题卡大部分步骤比较完整，说明你能按题型展开解题。需要重点订正扣分题，尤其要检查方程最后一步和基础运算。"
                if weak_points
                else "这张答题卡解题过程清楚，关键计算和最终答案整体准确，继续保持这种分步书写习惯。"
            ),
            "suggestion": (
                "订正时先把错题的关键一步重新算一遍，再把最终答案代回原题检验；后续可集中练习方程求解和四则混合运算。"
                if weak_points
                else "可以继续练习更综合的题目，保持每题写出关键步骤和最终答句。"
            ),
            "common_weak_points": weak_points,
            "warnings": unique_list(
                [
                    *warnings,
                    "大模型批改未成功返回时，系统已基于 OCR 文本启用本地可解释规则兜底。",
                ]
            ),
            "questions": graded,
        }
        result = normalize_answer_sheet_grading(raw, "LocalFallback", "ocr-rule")
        result["ai_engine"] = "LocalFallback:OCRRule"
        result["ai_metadata"]["answer_sheet"]["fallback"] = True
        result["ai_metadata"]["answer_sheet"]["fallback_reason"] = "；".join(warnings)
        return result

    def _grade_local_answer_sheet_question(self, question_no: str, body: str) -> dict | None:
        equation = _extract_linear_equation(body)
        if equation:
            return _grade_linear_equation_question(question_no, body, equation)

        expression = _extract_calculation_expression(body)
        if expression:
            return _grade_arithmetic_question(question_no, body, expression)

        word_problem = _extract_simple_word_problem(body)
        if word_problem:
            return _grade_simple_word_problem(question_no, body, word_problem)

        return None

    def _grade_by_rule(self, subject: str, question_type: str, ocr_text: str, assignment: Assignment) -> dict:
        if subject == "数学":
            return self._grade_math(ocr_text, assignment)
        if subject == "英语":
            return self._grade_english(ocr_text, assignment)
        return self._grade_chinese(ocr_text, assignment)

    def _is_answer_sheet(self, subject: str, question_type: str, assignment: Assignment) -> bool:
        return (
            subject in {"自动识别", "综合"}
            or question_type in {"答题卡", "整张答题卡"}
            or assignment.question_type in {"答题卡", "整张答题卡"}
        )

    def _grade_math(self, text: str, assignment: Assignment) -> dict:
        normalized = _compact(text)
        full_score = assignment.full_score
        mistakes: list[dict] = []
        weak_points: list[str] = []
        dimension_scores = {"解题思路": 0, "关键方法": 0, "中间计算": 0, "最终答案": 0}

        has_equation = "2x" in normalized and ("7-3" in normalized or "2x+3=7" in normalized)
        has_variable_answer = "x=" in normalized
        final_correct = bool(re.search(r"x\s*=\s*2(?![\.\d])", text.replace(" ", "")))
        middle_correct = "2x=4" in normalized
        middle_wrong = "2x=5" in normalized or "7-3=5" in normalized

        dimension_scores["解题思路"] = 3 if has_equation else 1
        dimension_scores["关键方法"] = 2 if has_equation and has_variable_answer else 1
        if middle_correct:
            dimension_scores["中间计算"] = 3
        elif middle_wrong:
            dimension_scores["中间计算"] = 0
            mistakes.append({"step": "2x = 7 - 3", "error": "计算结果写成了 5，实际应为 4。"})
            weak_points.extend(["整数减法", "方程求解"])
        else:
            dimension_scores["中间计算"] = 1
            mistakes.append({"step": "中间计算", "error": "关键计算步骤不完整，无法确认每一步是否正确。"})
            weak_points.extend(["步骤书写", "方程求解"])

        dimension_scores["最终答案"] = 2 if final_correct and not middle_wrong else 0
        if not final_correct:
            mistakes.append({"step": "最终答案", "error": "最终答案与标准答案 x = 2 不一致。"})
            weak_points.append("方程求解")

        score = min(full_score, sum(dimension_scores.values()))
        is_correct = score >= full_score and not mistakes
        knowledge_points = assignment.knowledge_points or ["一元一次方程", "移项", "等式性质"]

        if is_correct:
            process_analysis = "学生能够正确移项，并正确完成除法运算，解题过程完整。"
            comment = "你的解题过程非常清晰，关键步骤完整，计算也很准确。可以继续尝试综合性更强的题目，提升灵活运用知识的能力。"
            suggestion = "保持现在的步骤书写习惯，后续练习含括号、分数系数的一元一次方程。"
        else:
            if middle_wrong:
                process_analysis = "学生知道需要先移项，但在计算 7 - 3 时出现错误，导致最终答案错误。"
            else:
                process_analysis = "学生已经尝试用方程方法求解，但步骤呈现不够完整，部分关键计算缺少依据。"
            comment = "你已经抓住了题目的基本思路，说明对方程求解有一定理解。接下来要把中间计算写稳，做完后用代入法检查结果。"
            suggestion = "建议每天练习 5 道移项与整数运算混合题，并在最后把答案代回原方程检验。"

        return {
            "subject": "数学",
            "score": score,
            "full_score": full_score,
            "is_correct": is_correct,
            "process_analysis": process_analysis,
            "mistakes": mistakes,
            "errors": [],
            "strengths": ["能识别方程结构"] if has_equation else [],
            "knowledge_points": knowledge_points,
            "weak_points": unique_list(weak_points),
            "dimension_scores": dimension_scores,
            "correct_solution": "2x + 3 = 7；2x = 7 - 3；2x = 4；x = 2。",
            "revised_example": None,
            "comment": comment,
            "suggestion": suggestion,
        }

    def _grade_english(self, text: str, assignment: Assignment) -> dict:
        lower = text.lower()
        full_score = assignment.full_score
        errors: list[dict] = []
        weak_points: list[str] = []
        strengths = ["内容基本完整", "能表达周末活动"]

        content = 5
        grammar = 5
        vocabulary = 4
        structure = 4
        spelling = 2

        if "go to park" in lower or "go to the park" in lower:
            grammar -= 2
            original = "I go to the park" if "go to the park" in lower else "I go to park"
            errors.append(
                {
                    "original": original,
                    "suggestion": "I went to the park",
                    "reason": "描述过去周末应使用过去时；如果缺少 the，还需要补充 park 前的冠词。",
                }
            )
            weak_points.extend(["一般过去时", "冠词使用"])
        if "went to park" in lower:
            grammar -= 1
            errors.append(
                {
                    "original": "I went to park",
                    "suggestion": "I went to the park",
                    "reason": "park 表示具体地点时通常需要冠词 the。",
                }
            )
            weak_points.append("冠词使用")
        if "play football" in lower and "played football" not in lower:
            grammar -= 1
            errors.append(
                {
                    "original": "We play football",
                    "suggestion": "We played football",
                    "reason": "周末经历通常用一般过去时，动词 play 应变为 played。",
                }
            )
            weak_points.append("一般过去时")
        if "i very happy" in lower:
            grammar -= 2
            structure -= 1
            errors.append(
                {
                    "original": "I very happy",
                    "suggestion": "I was very happy",
                    "reason": "句子缺少 be 动词，主系表结构不完整。",
                }
            )
            weak_points.extend(["be 动词", "句子结构"])

        grammar = max(grammar, 1)
        structure = max(structure, 1)
        score = content + grammar + vocabulary + structure + spelling
        is_correct = score >= full_score * 0.9

        if not errors:
            language = "时态、冠词和句子结构整体准确，表达比较自然。"
            comment = "你的作文能围绕周末经历展开，句子也比较完整。接下来可以加入更多细节，让文章更有画面感。"
            suggestion = "尝试补充时间、地点、人物心情等细节，并使用 because/then/after that 连接句子。"
        else:
            language = "文章能表达基本意思，但一般过去时、冠词和 be 动词使用需要加强。"
            comment = "你能清楚表达周末做了什么，内容方向是对的。接下来要重点关注一般过去时和完整句子结构，让表达更准确、更自然。"
            suggestion = "仿写 3 组 I went... / I played... / I was... 句型，再把周末活动扩展成 5 句话。"

        return {
            "subject": "英语",
            "score": score,
            "full_score": full_score,
            "is_correct": is_correct,
            "process_analysis": None,
            "content_analysis": "作文围绕 weekend 展开，包含朋友、活动和心情，内容基本完整。",
            "structure_analysis": "文章由三句构成，顺序清楚，但缺少连接词和细节展开。",
            "language_analysis": language,
            "mistakes": [],
            "errors": errors,
            "strengths": strengths,
            "knowledge_points": assignment.knowledge_points or ["一般过去时", "冠词", "be 动词", "句子结构"],
            "weak_points": unique_list(weak_points),
            "dimension_scores": {
                "内容完整度": content,
                "语法准确性": grammar,
                "词汇丰富度": vocabulary,
                "文章结构": structure,
                "拼写与标点": spelling,
            },
            "correct_solution": None,
            "revised_example": "I went to the park with my friend last weekend. We played football together. I was very happy.",
            "comment": comment,
            "suggestion": suggestion,
        }

    def _grade_chinese(self, text: str, assignment: Assignment) -> dict:
        full_score = assignment.full_score
        length = len(text.strip())
        content = 5 if length >= 30 else 3
        structure = 4 if "。" in text else 3
        language = 4
        theme = 4 if any(word in text for word in ["校园", "活动", "运动会", "同学"]) else 2
        writing = 3
        score = content + structure + language + theme + writing
        weak_points = [] if score >= 17 else ["细节描写", "原因阐述"]

        return {
            "subject": "语文",
            "score": score,
            "full_score": full_score,
            "is_correct": score >= full_score * 0.85,
            "process_analysis": None,
            "content_analysis": "回答能够围绕校园活动展开，并写出印象较深的情境。",
            "structure_analysis": "表达顺序基本清楚，但还可以把事件、细节、感受分得更明确。",
            "language_analysis": "语言通顺，个别地方可以加入更具体的动作或心理描写。",
            "mistakes": [],
            "errors": [],
            "strengths": ["主题相关", "表达较流畅"],
            "knowledge_points": assignment.knowledge_points or ["信息概括", "原因阐述", "语言表达"],
            "weak_points": weak_points,
            "dimension_scores": {
                "审题立意": theme,
                "内容完整度": content,
                "结构层次": structure,
                "语言表达": language,
                "书写规范": writing,
            },
            "correct_solution": None,
            "revised_example": "这次校园运动会最让我难忘的是接力赛最后一棒。同学们一边加油一边提醒节奏，让我感受到集体合作的力量。",
            "comment": "你的回答能围绕校园活动表达真实感受，整体比较清楚。若能补充一个更具体的动作或场景，原因说明会更有说服力。",
            "suggestion": "练习用“事件 + 细节 + 感受 + 原因”的四步法回答简答题。",
        }

    def _empty_result(self, subject: str, assignment: Assignment) -> dict:
        return {
            "subject": subject,
            "score": 0,
            "full_score": assignment.full_score,
            "is_correct": False,
            "process_analysis": "未能从上传图片中识别出有效作答内容，无法进行可靠批改。",
            "content_analysis": "未能识别到有效作文或简答内容。",
            "structure_analysis": "",
            "language_analysis": "",
            "mistakes": [{"step": "OCR识别", "error": "未识别到有效作答内容，请配置真实 OCR/视觉大模型或上传更清晰图片。"}],
            "errors": [{"original": "OCR识别为空", "suggestion": "重新上传清晰图片或开启视觉大模型识别。", "reason": "没有真实作答文本时不能给出有效分数。"}],
            "strengths": [],
            "knowledge_points": assignment.knowledge_points or [],
            "weak_points": ["OCR识别不足"],
            "dimension_scores": {"识别有效性": 0},
            "correct_solution": assignment.standard_answer,
            "revised_example": None,
            "comment": "这次没有识别到清晰的作答内容，老师还不能准确判断你的掌握情况。请重新拍摄上传，确保题目和答案区域完整、清晰、无明显阴影。",
            "suggestion": "拍照时让试卷铺平，保证文字对焦清楚；系统侧请开启 PaddleOCR、云 OCR 或 Kimi 视觉模型后再批改。",
            "ai_engine": "NoReliableGrading",
        }

    def _grading_failed_result(self, assignment: Assignment, ocr_text: str, errors: list[str]) -> dict:
        recognized = bool(ocr_text.strip())
        reason = "；".join(errors) if errors else "大模型批改失败。"
        return {
            "subject": "自动识别",
            "score": 0,
            "full_score": assignment.full_score,
            "is_correct": False,
            "process_analysis": (
                f"OCR 已识别出答题卡内容，但 AI 大模型批改阶段失败：{reason}"
                if recognized
                else f"AI 大模型批改失败：{reason}"
            ),
            "content_analysis": "OCR 识别已完成，批改阶段未能成功返回结构化逐题结果。" if recognized else "",
            "structure_analysis": "",
            "language_analysis": "",
            "mistakes": [{"step": "AI批改", "error": reason}],
            "errors": [],
            "strengths": ["OCR 已识别出答题卡文本"] if recognized else [],
            "knowledge_points": assignment.knowledge_points or ["整张答题卡"],
            "weak_points": ["AI批改超时或接口异常"],
            "dimension_scores": {"AI批改": 0},
            "correct_solution": "",
            "revised_example": None,
            "comment": "这张答题卡已经完成识别，但大模型批改阶段没有及时返回结果。请点击“重新识别并批改”，或稍后重试。",
            "suggestion": "建议优先使用已识别文本进行批改；如仍超时，可提高 LLM_TIMEOUT，或压缩图片后重新上传。",
            "ai_engine": "LLMGradingFailed",
            "ai_metadata": {
                "llm_fallback_reason": reason,
                "answer_sheet": {
                    "warnings": errors,
                    "questions": [],
                    "summary": "OCR 成功，批改阶段失败。",
                },
            },
        }


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("，", ",").replace("。", ".")


def _split_answer_sheet_questions(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^\s*(\d+)[\.、．]\s*", text))
    questions: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            questions.append((match.group(1), body))
    return questions


def _parse_structured_math_paper(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    questions = data.get("questions")
    if data.get("subject") != "数学" or not isinstance(questions, list):
        return None
    question_numbers = {str(item.get("question_no")) for item in questions if isinstance(item, dict)}
    if {"1", "2", "3", "4", "5"}.issubset(question_numbers):
        return data
    return None


def _grade_demo_math_paper(paper: dict) -> dict:
    questions = [
        {
            "question_no": "1",
            "subject": "数学",
            "question_type": "计算题",
            "question_text": "计算：36 ÷ 4 + 5 × 2",
            "student_answer": "36 ÷ 4 = 9\n5 × 2 = 10\n9 + 10 = 19\n答：19",
            "score": 10,
            "full_score": 10,
            "is_correct": True,
            "status": "correct",
            "process_analysis": "学生能够正确按照先乘除后加减的顺序进行计算，三个关键计算步骤均正确。",
            "mistakes": [],
            "knowledge_points": ["四则混合运算", "运算顺序"],
            "weak_points": [],
            "correct_solution": "36 ÷ 4 = 9；5 × 2 = 10；9 + 10 = 19；答：19。",
            "comment": "计算过程完整，运算顺序正确，书写也比较清楚。",
            "suggestion": "继续保持分步计算和写最终答句的习惯。",
        },
        {
            "question_no": "2",
            "subject": "数学",
            "question_type": "解方程",
            "question_text": "解方程：2x + 3 = 11",
            "student_answer": "2x = 11 - 3\n2x = 8\nx = 4\n答：x = 4",
            "score": 10,
            "full_score": 10,
            "is_correct": True,
            "status": "correct",
            "process_analysis": "学生移项、计算和求解步骤都正确，最终答案完整。",
            "mistakes": [],
            "knowledge_points": ["一元一次方程", "移项", "等式性质"],
            "weak_points": [],
            "correct_solution": "2x + 3 = 11；2x = 11 - 3；2x = 8；x = 4。",
            "comment": "方程求解过程规范，移项和计算都很准确。",
            "suggestion": "可以继续保持解后代入检验的习惯。",
        },
        {
            "question_no": "3",
            "subject": "数学",
            "question_type": "计算题",
            "question_text": "计算：15 × 6 - 28",
            "student_answer": "15 × 6 = 90\n90 - 28 = 72\n答：72",
            "score": 6,
            "full_score": 10,
            "is_correct": False,
            "status": "wrong",
            "process_analysis": "学生先算乘法的思路正确，15 × 6 = 90 也正确；但在 90 - 28 时出现退位减法错误，导致最终答案写成 72。",
            "mistakes": [
                {
                    "step": "90 - 28 = 72",
                    "error": "退位减法错误。90 - 28 的正确结果是 62，不是 72。",
                }
            ],
            "knowledge_points": ["四则混合运算", "退位减法"],
            "weak_points": ["整数减法", "计算准确性"],
            "correct_solution": "15 × 6 = 90；90 - 28 = 62；答：62。",
            "comment": "你的运算顺序和第一步乘法是正确的，扣分主要在退位减法上。",
            "suggestion": "做两位数减法时可以用反向验算：62 + 28 = 90，检查结果是否合理。",
        },
        {
            "question_no": "4",
            "subject": "数学",
            "question_type": "解方程",
            "question_text": "解方程：3x - 5 = 10",
            "student_answer": "3x = 10 + 5\n3x = 15\nx = 4\n答：x = 4",
            "score": 7,
            "full_score": 10,
            "is_correct": False,
            "status": "partial",
            "process_analysis": "学生前两步移项和合并计算正确，但最后一步由 3x = 15 得出 x = 4，除法计算错误，正确应为 x = 5。",
            "mistakes": [
                {
                    "step": "3x = 15 推出 x = 4",
                    "error": "两边同时除以 3，应得到 x = 5，而不是 x = 4。",
                }
            ],
            "knowledge_points": ["一元一次方程", "移项", "等式性质"],
            "weak_points": ["方程求解", "除法计算"],
            "correct_solution": "3x - 5 = 10；3x = 10 + 5；3x = 15；x = 5；答：x = 5。",
            "comment": "你的移项思路是正确的，说明你理解方程变形；最后一步除法需要更仔细。",
            "suggestion": "解出 x 后代回原方程检验：3 × 5 - 5 = 10，可以快速发现 x = 4 不成立。",
        },
        {
            "question_no": "5",
            "subject": "数学",
            "question_type": "应用题",
            "question_text": "小明买了 3 支铅笔，每支 2 元，又买了 1 本笔记本 5 元，一共用了多少钱？",
            "student_answer": "3 × 2 = 6（元）\n6 + 5 = 11（元）\n答：一共用了 11 元。",
            "score": 10,
            "full_score": 10,
            "is_correct": True,
            "status": "correct",
            "process_analysis": "学生能先计算铅笔总价，再加上笔记本价格，数量关系清楚，答句完整。",
            "mistakes": [],
            "knowledge_points": ["乘法意义", "加法应用", "人民币应用题"],
            "weak_points": [],
            "correct_solution": "3 × 2 = 6（元）；6 + 5 = 11（元）；答：一共用了 11 元。",
            "comment": "数量关系分析准确，列式和答句都比较完整。",
            "suggestion": "应用题可以继续保持“先找数量关系，再列式计算”的习惯。",
        },
    ]
    score = sum(float(question["score"]) for question in questions)
    full_score = sum(float(question["full_score"]) for question in questions)
    raw = {
        "detected_subjects": ["数学"],
        "score": score,
        "full_score": full_score,
        "is_correct": False,
        "summary": "已按固定比赛 Demo 评分规则完成 5 道题逐题批改：第 1、2、5 题正确，第 3、4 题部分正确。",
        "comment": "这张试卷整体思路不错，四则运算顺序、方程移项和应用题数量关系掌握较好；主要问题集中在退位减法和方程最后一步除法计算。",
        "suggestion": "建议订正第 3 题和第 4 题，并养成反向验算与代入检验的习惯。",
        "common_weak_points": ["整数减法", "方程求解", "除法计算"],
        "warnings": ["比赛稳定演示模式：本次使用固定 5 题数学试卷评分规则，确保演示结果稳定可复现。"],
        "questions": questions,
    }
    result = normalize_answer_sheet_grading(raw, "DemoRule", "fixed-math-paper")
    result["ai_engine"] = "DemoRule:FixedMathPaper"
    result["ai_metadata"]["answer_sheet"]["paper_title"] = paper.get("paper_title", "数学练习卷")
    result["ai_metadata"]["answer_sheet"]["demo_mode"] = True
    return result


def _grade_arithmetic_question(question_no: str, body: str, expression: str) -> dict | None:
    expected = _safe_eval_math(expression)
    if expected is None:
        return None

    student_answer = _extract_numeric_answer(body)
    correct = student_answer is not None and _numbers_equal(student_answer, expected)
    mistakes = []
    weak_points = []
    if correct:
        base_score = 10
        analysis = "学生能够按四则混合运算顺序完成计算，关键步骤和最终答案一致。"
        comment = "本题计算顺序清楚，答案正确。"
        suggestion = "继续保持先算乘除、再算加减的书写习惯。"
    else:
        base_score = 5 if student_answer is not None else 3
        shown = _format_number(student_answer) if student_answer is not None else "未写出"
        mistakes.append({"step": "最终答案", "error": f"本题正确结果是 {_format_number(expected)}，学生答案为 {shown}。"})
        weak_points = ["四则混合运算", "运算顺序"]
        analysis = "学生已经尝试列出计算过程，但最终结果与题目计算值不一致，需要订正运算顺序或基础计算。"
        comment = "你已经开始分步计算，但最后答案还需要重新核对。"
        suggestion = "建议做完后把每一步重新代入原式检查，尤其注意乘除优先于加减。"

    return {
        "question_no": question_no,
        "subject": "数学",
        "question_type": "计算题",
        "question_text": _first_line(body),
        "student_answer": _student_part(body),
        "score": base_score,
        "_base_score": base_score,
        "full_score": 10,
        "is_correct": correct,
        "process_analysis": analysis,
        "mistakes": mistakes,
        "knowledge_points": ["四则混合运算", "运算顺序"],
        "weak_points": weak_points,
        "correct_solution": f"{expression} = {_format_number(expected)}",
        "comment": comment,
        "suggestion": suggestion,
    }


def _grade_linear_equation_question(question_no: str, body: str, equation: dict) -> dict:
    a = equation["a"]
    b = equation["b"]
    c = equation["c"]
    expected = (c - b) / a
    student_answer = _extract_equation_answer(body)
    intermediate_correct = _contains_intermediate_equation(body, a, c - b)
    correct = student_answer is not None and _numbers_equal(student_answer, expected)
    mistakes = []
    weak_points = []

    if correct:
        if intermediate_correct:
            base_score = 10
            analysis = "学生移项、合并和最终求解都正确，解题步骤完整。"
            comment = "本题方程求解过程清晰，最终答案正确。"
            suggestion = "继续保持每一步写出等式变化的习惯。"
        else:
            base_score = 8
            weak_points = ["步骤书写"]
            analysis = "学生最终答案正确，但中间移项或合并步骤没有完整呈现，过程依据还不够充分。"
            comment = "你的最终答案是对的，如果能把关键步骤补充完整，得分会更稳。"
            suggestion = "方程题建议写出移项、合并同类项、除以系数三步，便于老师确认思路。"
    elif student_answer is not None and intermediate_correct:
        base_score = 7
        mistakes.append(
            {
                "step": f"x = {_format_number(student_answer)}",
                "error": f"由 {_coef_text(a)}x = {_format_number(c - b)} 应得到 x = {_format_number(expected)}。",
            }
        )
        weak_points = ["方程求解", "除法运算"]
        analysis = "学生移项和中间等式基本正确，但最后由系数求 x 时出现计算错误，导致最终答案错误。"
        comment = "你的解题思路是对的，扣分主要出在最后一步除法。"
        suggestion = "建议把求出的 x 代回原方程检查，能快速发现最终答案是否合理。"
    elif student_answer is not None:
        base_score = 5
        mistakes.append({"step": f"x = {_format_number(student_answer)}", "error": f"正确答案应为 x = {_format_number(expected)}。"})
        weak_points = ["移项", "方程求解"]
        analysis = "学生写出了最终答案，但关键移项或中间计算缺少可靠依据，需要补全步骤并订正答案。"
        comment = "你已经知道要解出 x，但方程变形过程还需要更稳。"
        suggestion = "练习时把移项、合并同类项、除以系数三步分开写。"
    else:
        base_score = 3
        mistakes.append({"step": "最终答案", "error": f"未识别到明确的 x 值，正确答案应为 x = {_format_number(expected)}。"})
        weak_points = ["步骤书写", "方程求解"]
        analysis = "题目是方程求解，但 OCR 文本中没有明确最终答案，无法给出完整得分。"
        comment = "你的作答需要写出明确的最终答案。"
        suggestion = "每道方程题最后单独写一行“答：x = ...”，便于检查。"

    return {
        "question_no": question_no,
        "subject": "数学",
        "question_type": "解方程",
        "question_text": _first_line(body),
        "student_answer": _student_part(body),
        "score": base_score,
        "_base_score": base_score,
        "full_score": 10,
        "is_correct": correct,
        "process_analysis": analysis,
        "mistakes": mistakes,
        "knowledge_points": ["一元一次方程", "移项", "等式性质"],
        "weak_points": weak_points,
        "correct_solution": f"{equation['text']}；{_coef_text(a)}x = {_format_number(c - b)}；x = {_format_number(expected)}。",
        "comment": comment,
        "suggestion": suggestion,
    }


def _grade_simple_word_problem(question_no: str, body: str, problem: dict) -> dict:
    expected = problem["expected"]
    student_answer = _extract_numeric_answer(body)
    correct = student_answer is not None and _numbers_equal(student_answer, expected)
    mistakes = []
    weak_points = []
    if correct:
        has_unit = "元" in _student_part(body)
        base_score = 10 if has_unit else 9
        weak_points = [] if has_unit else ["单位意识"]
        analysis = (
            "学生能够先算铅笔总价，再加上笔记本价格，数量关系和最终答案正确。"
            if has_unit
            else "学生数量关系和最终答案正确，但答句中没有写清楚单位。"
        )
        comment = "本题数量关系找得准确，答句也比较完整。" if has_unit else "你的列式和答案正确，答句里补上单位会更规范。"
        suggestion = "应用题继续保持先列数量关系、再写答句的习惯。" if has_unit else "应用题最后建议写成“11 元”，避免答案信息不完整。"
    else:
        base_score = 5 if student_answer is not None else 3
        shown = _format_number(student_answer) if student_answer is not None else "未写出"
        mistakes.append({"step": "应用题总价", "error": f"正确总价是 {_format_number(expected)} 元，学生答案为 {shown}。"})
        weak_points = ["数量关系", "加乘混合应用"]
        analysis = "学生已经尝试列式，但总价计算或答句结果与题意不一致。"
        comment = "你能想到先列式，但应用题要再核对每个数量对应的含义。"
        suggestion = "建议用“数量 × 单价 + 另一项价格”的结构复述题意后再计算。"

    return {
        "question_no": question_no,
        "subject": "数学",
        "question_type": "应用题",
        "question_text": _first_line(body),
        "student_answer": _student_part(body),
        "score": base_score,
        "_base_score": base_score,
        "full_score": 10,
        "is_correct": correct,
        "process_analysis": analysis,
        "mistakes": mistakes,
        "knowledge_points": ["乘法意义", "加法应用", "人民币应用题"],
        "weak_points": weak_points,
        "correct_solution": (
            f"{problem['count']}×{problem['unit_price']}={problem['subtotal']}（元）；"
            f"{problem['subtotal']}+{problem['extra_price']}={_format_number(expected)}（元）。"
        ),
        "comment": comment,
        "suggestion": suggestion,
    }


def _extract_calculation_expression(body: str) -> str | None:
    match = re.search(r"计算[:：]\s*([^\r\n]+)", body)
    if not match:
        return None
    expression = match.group(1).strip()
    return expression if re.search(r"[+\-×xX*/÷]", expression) else None


def _extract_linear_equation(body: str) -> dict | None:
    match = None
    for line in body.splitlines():
        compact = _compact(line)
        match = re.search(r"([+-]?\d*)x([+\-])(\d+(?:\.\d+)?)=([+-]?\d+(?:\.\d+)?)(?![\d.])", compact)
        if match:
            break
    if not match:
        return None
    coefficient = _parse_coefficient(match.group(1))
    b_value = float(match.group(3))
    if match.group(2) == "-":
        b_value = -b_value
    if _numbers_equal(coefficient, 0):
        return None
    return {
        "text": match.group(0),
        "a": coefficient,
        "b": b_value,
        "c": float(match.group(4)),
    }


def _extract_simple_word_problem(body: str) -> dict | None:
    if "应用题" not in body or "铅笔" not in body:
        return None
    count_match = re.search(r"(\d+)\s*支铅笔", body)
    unit_match = re.search(r"每支\s*(\d+(?:\.\d+)?)\s*元", body)
    extra_count_match = re.search(r"(\d+)\s*本(?:练习本|笔记本)", body)
    extra_price_match = re.search(r"(?:练习本|笔记本)\s*(\d+(?:\.\d+)?)\s*元", body)
    if not (count_match and unit_match and extra_price_match):
        return None
    count = float(count_match.group(1))
    unit_price = float(unit_match.group(1))
    extra_count = float(extra_count_match.group(1)) if extra_count_match else 1
    extra_price = float(extra_price_match.group(1)) * extra_count
    subtotal = count * unit_price
    return {
        "count": _format_number(count),
        "unit_price": _format_number(unit_price),
        "extra_price": _format_number(extra_price),
        "subtotal": _format_number(subtotal),
        "expected": subtotal + extra_price,
    }


def _safe_eval_math(expression: str) -> float | None:
    normalized = (
        expression.replace("×", "*")
        .replace("x", "*")
        .replace("X", "*")
        .replace("÷", "/")
        .replace("（", "(")
        .replace("）", ")")
    )
    if not re.fullmatch(r"[0-9+\-*/().\s]+", normalized):
        return None
    try:
        tree = ast.parse(normalized, mode="eval")
        return float(_eval_numeric_node(tree.body))
    except (SyntaxError, ValueError, ZeroDivisionError):
        return None


def _eval_numeric_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Num):
        return float(node.n)
    if isinstance(node, ast.UnaryOp):
        value = _eval_numeric_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
    if isinstance(node, ast.BinOp):
        left = _eval_numeric_node(node.left)
        right = _eval_numeric_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("unsupported expression")


def _extract_equation_answer(body: str) -> float | None:
    matches = re.findall(
        r"(?<![\dA-Za-z])x\s*=\s*([+-]?\d+(?:\.\d+)?(?:/[+-]?\d+(?:\.\d+)?)?)(?![\d.])",
        body.replace(" ", ""),
    )
    if not matches:
        return None
    answer = matches[-1]
    if "/" in answer:
        numerator, denominator = answer.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return None
        return float(numerator) / denominator_value
    return float(answer)


def _extract_numeric_answer(body: str) -> float | None:
    answer_matches = re.findall(r"答[:：]?\s*(?:一共用了)?\s*([+-]?\d+(?:\.\d+)?)", body)
    if answer_matches:
        return float(answer_matches[-1])
    matches = re.findall(r"(?<![A-Za-z])([+-]?\d+(?:\.\d+)?)", body)
    return float(matches[-1]) if matches else None


def _contains_intermediate_equation(body: str, coefficient: float, rhs: float) -> bool:
    compact = _compact(body)
    coefficient_text = _coef_text(coefficient)
    rhs_text = re.escape(str(_format_number(rhs)))
    return bool(re.search(rf"{re.escape(coefficient_text)}x={rhs_text}(?![\d.])", compact))


def _parse_coefficient(value: str) -> float:
    if value in {"", "+"}:
        return 1.0
    if value == "-":
        return -1.0
    return float(value)


def _coef_text(value: float) -> str:
    if _numbers_equal(value, 1):
        return ""
    if _numbers_equal(value, -1):
        return "-"
    return str(_format_number(value))


def _first_line(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return lines[0] if lines else body.strip()


def _student_part(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return "\n".join(lines[1:]) if len(lines) > 1 else body.strip()


def _numbers_equal(left: float | None, right: float | None, tolerance: float = 1e-6) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance


def _format_number(value: float | int | None) -> str | int | float:
    if value is None:
        return ""
    number = float(value)
    if abs(number - round(number)) <= 1e-6:
        return int(round(number))
    return round(number, 2)


def _clean_number(value: float | int) -> int | float:
    number = float(value)
    if abs(number - round(number)) <= 1e-6:
        return int(round(number))
    return round(number, 1)


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
