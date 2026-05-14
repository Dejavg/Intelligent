from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from ..models import Assignment, GradingResult, Submission, User


class ReportService:
    def student_report(self, db: Session, student_id: int) -> dict:
        student = db.query(User).filter(User.id == student_id, User.role == "student").first()
        if not student:
            raise ValueError("student not found")

        submissions = (
            db.query(Submission)
            .filter(Submission.student_id == student_id)
            .order_by(Submission.created_at.desc())
            .all()
        )
        total_score = 0.0
        total_full_score = 0.0
        weak_counter: Counter[str] = Counter()
        mistake_counter: Counter[str] = Counter()
        knowledge_counter: Counter[str] = Counter()
        questions: list[dict] = []

        for submission in submissions:
            assignment = submission.assignment
            result = submission.grading_result
            score = _effective_score(submission)
            total_score += score
            total_full_score += assignment.full_score
            if result:
                weak_counter.update(result.weak_points or [])
                knowledge_counter.update(result.knowledge_points or [])
                for mistake in result.mistakes or result.errors or []:
                    key = _mistake_text(mistake)
                    if key:
                        mistake_counter[key] += 1
            questions.append(_submission_summary(submission))

        weak_points = [
            {
                "knowledge_point": point,
                "error_count": count,
                "mastery_level": "较弱" if count >= 2 else "一般",
                "suggestion": _knowledge_suggestion(point),
            }
            for point, count in weak_counter.most_common()
        ]

        return {
            "student_id": student.id,
            "student_name": student.name,
            "class_name": student.class_name,
            "total_score": round(total_score, 1),
            "total_full_score": round(total_full_score, 1),
            "score_rate": f"{round(total_score / total_full_score * 100, 1)}%" if total_full_score else "0%",
            "questions": questions,
            "score_trend": _score_trend(submissions),
            "trend_summary": _trend_summary(submissions),
            "knowledge_mastery": _knowledge_mastery(knowledge_counter, weak_counter),
            "error_distribution": [
                {"mistake": mistake, "count": count}
                for mistake, count in mistake_counter.most_common(8)
            ],
            "weak_points": weak_points,
            "personal_suggestion": _student_suggestion(weak_points),
        }

    def class_analysis(self, db: Session, class_name: str) -> dict:
        students = db.query(User).filter(User.class_name == class_name, User.role == "student").all()
        student_ids = [student.id for student in students]
        submissions = db.query(Submission).filter(Submission.student_id.in_(student_ids)).all() if student_ids else []

        scores = [_effective_score(submission) for submission in submissions]
        full_scores = [submission.assignment.full_score for submission in submissions]
        average_score = round(sum(scores) / len(scores), 1) if scores else 0
        highest_score = round(max(scores), 1) if scores else 0
        lowest_score = round(min(scores), 1) if scores else 0
        correct_count = 0
        weak_counter: Counter[str] = Counter()
        mistake_counter: Counter[str] = Counter()
        student_buckets: dict[int, dict] = {
            student.id: {
                "student": student,
                "score": 0.0,
                "full_score": 0.0,
                "submissions": 0,
                "weak_points": Counter(),
            }
            for student in students
        }
        question_stat: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

        for submission in submissions:
            result = submission.grading_result
            assignment = submission.assignment
            bucket = student_buckets.get(submission.student_id)
            if bucket:
                bucket["score"] += _effective_score(submission)
                bucket["full_score"] += float(assignment.full_score or 0)
                bucket["submissions"] += 1
            stat = question_stat[assignment.title]
            stat["total"] += 1
            if result and result.is_correct:
                correct_count += 1
                stat["correct"] += 1
            if result:
                weak_counter.update(result.weak_points or [])
                if bucket:
                    bucket["weak_points"].update(result.weak_points or [])
                for mistake in result.mistakes or result.errors or []:
                    key = _mistake_text(mistake) or "表达不完整"
                    mistake_counter[key] += 1

        total_submissions = len(submissions)
        accuracy_rate = round(correct_count / total_submissions * 100, 1) if total_submissions else 0
        question_accuracy = [
            {
                "question": title,
                "accuracy": round(value["correct"] / value["total"] * 100, 1) if value["total"] else 0,
                "total": value["total"],
            }
            for title, value in question_stat.items()
        ]

        common_weak_points = [
            {"knowledge_point": point, "count": count, "suggestion": _knowledge_suggestion(point)}
            for point, count in weak_counter.most_common(8)
        ]

        return {
            "class_name": class_name,
            "total_students": len(students),
            "total_submissions": total_submissions,
            "average_score": average_score,
            "highest_score": highest_score,
            "lowest_score": lowest_score,
            "accuracy_rate": f"{accuracy_rate}%",
            "average_score_rate": f"{round(sum(scores) / sum(full_scores) * 100, 1)}%" if sum(full_scores) else "0%",
            "question_accuracy": question_accuracy,
            "common_weak_points": common_weak_points,
            "frequent_mistakes": [
                {"mistake": mistake, "count": count}
                for mistake, count in mistake_counter.most_common(6)
            ],
            "layer_analysis": _layer_analysis(student_buckets.values()),
            "student_comparison": _student_comparison(student_buckets.values()),
            "teacher_suggestion": _teacher_suggestion(common_weak_points),
            "submissions": [_submission_summary(submission) for submission in submissions],
        }


def _effective_score(submission: Submission) -> float:
    if submission.teacher_score is not None:
        return float(submission.teacher_score)
    if submission.ai_score is not None:
        return float(submission.ai_score)
    return 0.0


def _submission_summary(submission: Submission) -> dict:
    assignment: Assignment = submission.assignment
    result: GradingResult | None = submission.grading_result
    return {
        "id": submission.id,
        "student_id": submission.student_id,
        "student_name": submission.student.name if submission.student else "",
        "class_name": submission.student.class_name if submission.student else "",
        "assignment_id": assignment.id,
        "assignment_title": assignment.title,
        "question": assignment.question,
        "subject": submission.subject,
        "question_type": submission.question_type,
        "status": submission.status,
        "image_url": submission.image_url,
        "ocr_text": submission.ocr_text,
        "ai_score": submission.ai_score,
        "teacher_score": submission.teacher_score,
        "effective_score": _effective_score(submission),
        "full_score": assignment.full_score,
        "score_rate": _score_rate(_effective_score(submission), assignment.full_score),
        "is_correct": result.is_correct if result else False,
        "weak_points": result.weak_points if result else [],
        "comment": result.comment if result else "",
        "suggestion": result.suggestion if result else "",
        "created_at": submission.created_at.isoformat() if submission.created_at else "",
    }


def _score_trend(submissions: list[Submission]) -> list[dict]:
    ordered = sorted(submissions, key=lambda item: item.created_at or 0)
    return [
        {
            "submission_id": submission.id,
            "assignment_title": submission.assignment.title,
            "created_at": submission.created_at.isoformat() if submission.created_at else "",
            "score": round(_effective_score(submission), 1),
            "full_score": submission.assignment.full_score,
            "score_rate": _score_rate(_effective_score(submission), submission.assignment.full_score),
        }
        for submission in ordered
    ]


def _trend_summary(submissions: list[Submission]) -> dict:
    trend = _score_trend(submissions)
    if len(trend) < 2:
        return {"direction": "数据不足", "delta": 0, "message": "完成更多作业后可形成学习趋势。"}
    first = trend[0]["score_rate"]
    last = trend[-1]["score_rate"]
    delta = round(last - first, 1)
    if delta >= 5:
        direction = "进步"
        message = f"最近得分率较早期提升 {delta} 个百分点，建议保持当前订正节奏。"
    elif delta <= -5:
        direction = "下滑"
        message = f"最近得分率较早期下降 {abs(delta)} 个百分点，建议优先复盘近期错题。"
    else:
        direction = "稳定"
        message = "近期得分率整体稳定，可针对薄弱知识点做专项突破。"
    return {"direction": direction, "delta": delta, "message": message}


def _knowledge_mastery(knowledge_counter: Counter[str], weak_counter: Counter[str]) -> list[dict]:
    points = set(knowledge_counter) | set(weak_counter)
    mastery = []
    for point in points:
        total = max(knowledge_counter.get(point, 0), weak_counter.get(point, 0), 1)
        weak = weak_counter.get(point, 0)
        rate = max(0, round((1 - weak / (total + weak)) * 100, 1))
        mastery.append(
            {
                "knowledge_point": point,
                "mastery_rate": rate,
                "level": "优秀" if rate >= 85 else "一般" if rate >= 65 else "较弱",
                "weak_count": weak,
                "suggestion": _knowledge_suggestion(point),
            }
        )
    return sorted(mastery, key=lambda item: item["mastery_rate"])


def _layer_analysis(buckets) -> list[dict]:
    layers = [
        {"name": "提升层", "range": "85% 及以上", "students": [], "suggestion": "安排综合拓展题，提升迁移应用与表达规范。"},
        {"name": "稳固层", "range": "70%-85%", "students": [], "suggestion": "保持基础正确率，针对高频错因做小专题巩固。"},
        {"name": "帮扶层", "range": "70% 以下", "students": [], "suggestion": "优先讲清基础概念和关键步骤，减少一次性任务量。"},
    ]
    for bucket in buckets:
        full_score = float(bucket["full_score"] or 0)
        rate = round(float(bucket["score"]) / full_score * 100, 1) if full_score else 0
        student = bucket["student"]
        item = {
            "student_id": student.id,
            "student_name": student.name,
            "score_rate": rate,
            "submission_count": bucket["submissions"],
            "main_weak_points": [point for point, _ in bucket["weak_points"].most_common(3)],
        }
        if rate >= 85:
            layers[0]["students"].append(item)
        elif rate >= 70:
            layers[1]["students"].append(item)
        else:
            layers[2]["students"].append(item)
    for layer in layers:
        layer["count"] = len(layer["students"])
    return layers


def _student_comparison(buckets) -> list[dict]:
    rows = []
    for bucket in buckets:
        student = bucket["student"]
        full_score = float(bucket["full_score"] or 0)
        rate = round(float(bucket["score"]) / full_score * 100, 1) if full_score else 0
        rows.append(
            {
                "student_id": student.id,
                "student_name": student.name,
                "score": round(float(bucket["score"]), 1),
                "full_score": round(full_score, 1),
                "score_rate": rate,
                "submission_count": bucket["submissions"],
                "main_weak_points": [point for point, _ in bucket["weak_points"].most_common(3)],
            }
        )
    return sorted(rows, key=lambda item: item["score_rate"], reverse=True)


def _score_rate(score: float, full_score: float) -> float:
    return round(float(score) / float(full_score) * 100, 1) if full_score else 0.0


def _mistake_text(mistake) -> str:
    if isinstance(mistake, str):
        return mistake
    if isinstance(mistake, dict):
        return str(mistake.get("error") or mistake.get("reason") or mistake.get("original") or mistake.get("step") or "")
    return ""


def _knowledge_suggestion(point: str) -> str:
    mapping = {
        "一元一次方程": "复习等式性质和移项规则，并完成 5 道基础方程练习。",
        "整数减法": "加强整数加减法口算训练，写完关键算式后反向验算。",
        "方程求解": "用“移项、合并、系数化为 1、代入检验”四步法练习。",
        "选择题审题": "先圈出题干关键词，再逐项排除干扰选项。",
        "填空题答案规范": "填空题完成后检查单位、大小写、格式和是否漏空。",
        "一般过去时": "整理常见动词过去式，并用过去时描述 3 件周末活动。",
        "冠词使用": "复习 a/an/the 的使用场景，尤其是地点名词前的 the。",
        "be 动词": "练习主语与 was/were 的搭配，补全主系表句子。",
        "句子结构": "先保证每句话有主语和谓语，再逐步增加修饰成分。",
        "细节描写": "回答主观题时加入一个具体动作、场景或心理活动。",
        "原因阐述": "用“因为……所以……”或“这说明……”把理由写完整。",
    }
    return mapping.get(point, "针对该知识点完成基础复习和 3 道同类练习。")


def _student_suggestion(weak_points: list[dict]) -> str:
    if not weak_points:
        return "本次作业整体掌握较好，可以尝试更综合的题目，提升迁移运用能力。"
    first = weak_points[0]["knowledge_point"]
    return f"当前最需要关注的是“{first}”。建议先复盘错因，再完成少量同类练习并及时订正。"


def _teacher_suggestion(common_weak_points: list[dict]) -> str:
    if not common_weak_points:
        return "本次作业整体表现较稳定，可安排学生进行分层拓展练习。"
    names = "、".join(item["knowledge_point"] for item in common_weak_points[:3])
    return f"本次作业中，{names} 暴露较集中。建议下节课安排 8-10 分钟针对性讲解，并配合分层订正任务。"
