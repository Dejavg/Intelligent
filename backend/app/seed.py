from sqlalchemy.orm import Session

from .models import Assignment, ClassRoom, GradingResult, KnowledgePoint, Submission, User


STUDENTS = [
    {"name": "张三", "role": "student", "class_name": "七年级一班"},
    {"name": "李四", "role": "student", "class_name": "七年级一班"},
    {"name": "王五", "role": "student", "class_name": "七年级一班"},
]

ASSIGNMENTS = [
    {
        "title": "一元一次方程基础练习",
        "subject": "数学",
        "question_type": "计算题",
        "question": "解方程 2x + 3 = 7，求 x。",
        "standard_answer": "x = 2",
        "full_score": 10,
        "knowledge_points": ["一元一次方程", "移项", "等式性质"],
    },
    {
        "title": "数学应用题过程分析",
        "subject": "数学",
        "question_type": "应用题",
        "question": "小明买 2 支笔和 1 本练习本共 7 元，练习本 3 元，每支笔多少元？",
        "standard_answer": "每支笔 2 元",
        "full_score": 10,
        "knowledge_points": ["一元一次方程", "数量关系", "基础计算"],
    },
    {
        "title": "Weekend Writing",
        "subject": "英语",
        "question_type": "作文",
        "question": "Write a short passage about your weekend.",
        "standard_answer": "Use past tense to describe weekend activities clearly.",
        "full_score": 20,
        "knowledge_points": ["一般过去时", "冠词", "be 动词", "句子结构"],
    },
    {
        "title": "阅读简答：校园活动",
        "subject": "语文",
        "question_type": "简答题",
        "question": "请简要概括一次校园活动中让你印象最深的细节，并说明原因。",
        "standard_answer": "围绕校园活动，概括具体细节并说明原因，表达清楚即可。",
        "full_score": 20,
        "knowledge_points": ["信息概括", "原因阐述", "语言表达"],
    },
]

KNOWLEDGE_POINTS = [
    ("数学", "一元一次方程", "理解未知数、移项、合并同类项并求解。"),
    ("数学", "移项", "利用等式性质将含未知数项与常数项分离。"),
    ("数学", "等式性质", "等式两边同加减乘除同一个数后仍相等。"),
    ("数学", "基础计算", "整数、小数、分数的基础运算准确性。"),
    ("数学", "数量关系", "从应用题语境中建立等量关系。"),
    ("英语", "一般过去时", "描述过去发生的事情时正确使用动词过去式。"),
    ("英语", "冠词", "在可数名词前正确使用 a/an/the。"),
    ("英语", "be 动词", "根据主语和时态补全 am/is/are/was/were。"),
    ("英语", "句子结构", "主谓宾或主系表结构完整。"),
    ("语文", "信息概括", "提炼材料或经历中的关键内容。"),
    ("语文", "原因阐述", "围绕观点给出清楚、具体的理由。"),
    ("语文", "语言表达", "句意连贯，表达准确自然。"),
]


def seed_data(db: Session) -> None:
    if db.query(ClassRoom).count() == 0:
        db.add(ClassRoom(name="七年级一班", grade="七年级", teacher_name="陈老师"))

    if db.query(User).count() == 0:
        db.add_all(User(**student) for student in STUDENTS)
        db.add(User(name="陈老师", role="teacher", class_name="七年级一班"))

    if db.query(Assignment).count() == 0:
        db.add_all(Assignment(**assignment) for assignment in ASSIGNMENTS)

    if db.query(KnowledgePoint).count() == 0:
        db.add_all(
            KnowledgePoint(subject=subject, name=name, description=description)
            for subject, name, description in KNOWLEDGE_POINTS
        )

    db.commit()
    seed_demo_submissions(db)


def seed_demo_submissions(db: Session) -> None:
    if db.query(Submission).count() > 0:
        return

    zhang = db.query(User).filter(User.name == "张三").first()
    li = db.query(User).filter(User.name == "李四").first()
    wang = db.query(User).filter(User.name == "王五").first()
    math_assignment = db.query(Assignment).filter(Assignment.subject == "数学", Assignment.question_type == "计算题").first()
    english_assignment = db.query(Assignment).filter(Assignment.subject == "英语").first()

    demo_rows = [
        (
            zhang,
            math_assignment,
            "2x = 7 - 3\n2x = 4\nx = 2",
            10,
            True,
            "学生能够正确移项，并正确完成除法运算，解题过程完整。",
            [],
            ["一元一次方程", "移项", "等式性质"],
            [],
            "你的解题过程非常清晰，关键步骤完整，计算也很准确。可以继续尝试综合性更强的题目，提升灵活运用知识的能力。",
            "保持步骤书写习惯，后续可挑战含括号或分数系数的方程。",
        ),
        (
            li,
            math_assignment,
            "2x = 7 - 3\n2x = 5\nx = 2.5",
            6,
            False,
            "学生知道需要先移项，但在计算 7 - 3 时出现错误，导致最终答案错误。",
            [{"step": "2x = 7 - 3", "error": "计算结果写成了 5，实际应为 4。"}],
            ["一元一次方程", "基础计算"],
            ["整数减法", "方程求解"],
            "你已经掌握了先移项再求解的基本思路，不过中间计算出现了小偏差。建议做题后回看关键算式，尤其检查加减法结果。",
            "每天完成 5 道一元一次方程基础题，并用代入法检查答案。",
        ),
        (
            wang,
            english_assignment,
            "I go to park with my friend. We play football. I very happy.",
            13,
            False,
            "作文能围绕周末活动展开，但过去时、冠词和 be 动词使用不够准确。",
            [
                {
                    "original": "I go to park",
                    "suggestion": "I went to the park",
                    "reason": "描述过去周末应使用过去时，同时 park 前需要冠词 the。",
                },
                {
                    "original": "I very happy",
                    "suggestion": "I was very happy",
                    "reason": "句子缺少 be 动词。",
                },
            ],
            ["一般过去时", "冠词", "be 动词", "句子结构"],
            ["一般过去时", "冠词使用", "be 动词"],
            "你能清楚表达周末做了什么，内容方向是对的。接下来要重点关注一般过去时和完整句子结构，让表达更准确、更自然。",
            "仿写 3 组 I went... / I played... / I was... 句型，再把周末活动扩展成 5 句话。",
        ),
    ]

    for student, assignment, ocr_text, score, is_correct, analysis, mistakes, knowledge, weak, comment, suggestion in demo_rows:
        submission = Submission(
            student_id=student.id,
            assignment_id=assignment.id,
            subject=assignment.subject,
            question_type=assignment.question_type,
            image_url="",
            image_name="demo_sample.png",
            ocr_text=ocr_text,
            ai_score=score,
            status="AI 已批改",
        )
        db.add(submission)
        db.flush()
        db.add(
            GradingResult(
                submission_id=submission.id,
                is_correct=is_correct,
                process_analysis=analysis,
                content_analysis=analysis if assignment.subject in {"英语", "语文"} else None,
                mistakes=mistakes if assignment.subject == "数学" else [],
                errors=mistakes if assignment.subject in {"英语", "语文"} else [],
                strengths=["内容基本完整", "能围绕主题表达"] if assignment.subject == "英语" else [],
                knowledge_points=knowledge,
                weak_points=weak,
                dimension_scores={"总分": score, "满分": assignment.full_score},
                correct_solution="2x + 3 = 7；2x = 4；x = 2。" if assignment.subject == "数学" else None,
                revised_example="I went to the park with my friend. We played football. I was very happy." if assignment.subject == "英语" else None,
                comment=comment,
                suggestion=suggestion,
            )
        )

    db.commit()
