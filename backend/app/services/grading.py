from __future__ import annotations

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
        if not image_path:
            result = self._empty_result("自动识别", assignment)
            result["process_analysis"] = "整张答题卡批改需要上传包含题目与作答的图片。"
            return result
        if not (settings.llm_enabled and self.llm_client.vision_available):
            result = self._empty_result("自动识别", assignment)
            result["process_analysis"] = "整张答题卡批改需要启用视觉大模型。"
            result["suggestion"] = "请在 .env 中配置 LLM_ENABLED=true、OCR_PROVIDER=llm、KIMI_API_KEY 和 LLM_VISION_MODEL。"
            return result
        try:
            llm_result = self.llm_client.grade_answer_sheet(image_path, ocr_text, assignment)
            return normalize_answer_sheet_grading(llm_result.data, llm_result.provider, llm_result.model)
        except Exception as exc:
            result = self._empty_result("自动识别", assignment)
            result["process_analysis"] = f"整张答题卡大模型批改失败：{exc}"
            result["suggestion"] = "请检查大模型接口、图片清晰度、图片大小和模型是否支持视觉输入。"
            result["ai_metadata"] = {"llm_fallback_reason": str(exc)}
            return result

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

        if "go to park" in lower:
            grammar -= 2
            errors.append(
                {
                    "original": "I go to park",
                    "suggestion": "I went to the park",
                    "reason": "描述过去周末应使用过去时，同时 park 前需要冠词 the。",
                }
            )
            weak_points.extend(["一般过去时", "冠词使用"])
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


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("，", ",").replace("。", ".")


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
