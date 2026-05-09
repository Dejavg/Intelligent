# 技术说明文档

## 一、总体架构

希沃智评采用前后端分离的职责设计：

- 前端 SPA：负责学生上传、批改结果展示、教师复核、班级分析交互。
- FastAPI 后端：提供 RESTful API、数据持久化、OCR 调度、AI 批改、报告生成。
- SQLite 数据库：存储用户、作业、提交、批改结果和知识点。
- AI 服务层：`OCRService`、`GradingService`、`ReportService` 均为可替换模块。

核心流程：

```text
图片上传 -> 创建提交 -> OCR 识别 -> 结构化批改 -> 知识点归因 -> 学生报告/班级报告 -> 教师复核
```

## 二、OCR 方案

`backend/app/services/ocr.py` 中的 `OCRService` 已实现可配置 Provider。现在推荐比赛演示使用 `llm`，由 Kimi 视觉模型直接识别上传图片；也可以通过 `.env` 切换传统 OCR 服务：

```env
OCR_PROVIDER=llm       # mock | paddle | baidu | tencent | llm
ALLOW_MOCK_FOR_UPLOADED_IMAGES=false
FORMULA_OCR_PROVIDER=mock  # mock | mathpix | pix2tex | latex-ocr
```

接口返回结构为：

```json
{
  "raw_text": "识别出的完整文本",
  "confidence": 0.93,
  "blocks": [
    { "type": "formula", "text": "2x + 3 = 7", "confidence": 0.94 }
  ],
  "engine": "MockOCR",
  "formula_latex": "2x + 3 = 7, x = 2"
}
```

后续真实接入建议：

- 中文/英文手写：已预留 PaddleOCR、本地包可用时直接调用；百度 OCR 通过手写识别接口调用；腾讯 OCR 通过官方 Python SDK 调用。
- 数学公式：已预留 Mathpix HTTP 调用、pix2tex/LaTeX-OCR 本地模型调用。
- 版面分析：先检测题号、答案区域、步骤区域，再分别识别。
- 多图合并：按页码和题号归并 OCR 块，形成题目级文本。

替换方式：

1. 保持 `OCRService.recognize(submission, assignment)` 方法签名不变。
2. 将图片路径 `submission.image_url` 转成本地文件路径或对象存储 URL。
3. 调用真实 OCR 后返回同样结构的 `OCRResult`。

如果真实 OCR 依赖或密钥缺失，系统默认回退 Mock OCR，并在 `warnings` 字段说明回退原因。
对于真实上传图片，建议设置 `OCR_FALLBACK_TO_MOCK=false` 和 `ALLOW_MOCK_FOR_UPLOADED_IMAGES=false`。这样配置缺失时系统会给出“未配置真实 OCR/视觉大模型”的提示，而不是用样例答案打满分。

## 三、知识点建模方案

数据库表：

- `knowledge_points`：知识点主数据，包含学科、名称、说明。
- `assignments.knowledge_points`：每道题绑定一个或多个知识点。
- `grading_results.weak_points`：批改后记录学生暴露的薄弱点。

建模策略：

- 题目级知识点：由教师或题库预先标注，例如“一元一次方程、移项、等式性质”。
- 错因级薄弱点：批改时根据错误类型映射，例如 `2x = 5` 映射为“整数减法、方程求解”。
- 学生级统计：汇总该学生所有错题的 `weak_points`，生成掌握等级和建议。
- 班级级统计：聚合班级所有提交，计算高频薄弱点、错误分布和教学建议。

掌握等级示例：

```text
错误次数 >= 2：较弱
错误次数 = 1：一般
无集中错误：掌握较好
```

## 四、数学评分策略

数学批改位于 `GradingService._grade_math`，当前以一元一次方程样例为核心。

满分 10 分拆分：

| 维度 | 分值 | 判断方式 |
| --- | ---: | --- |
| 解题思路 | 3 | 是否写出方程变形或移项结构 |
| 关键方法 | 2 | 是否出现 `2x`、`x =` 等求解步骤 |
| 中间计算 | 3 | 是否正确得到 `2x = 4` |
| 最终答案 | 2 | 是否得到 `x = 2` |

输出内容：

- `score`：总分。
- `is_correct`：是否满分且无错误。
- `process_analysis`：过程分析。
- `mistakes`：错误位置和原因。
- `correct_solution`：标准解法。
- `knowledge_points`：题目知识点。
- `weak_points`：薄弱点归因。
- `comment` 和 `suggestion`：个性化评语与建议。

后续可升级为：

- SymPy 校验中间等式是否等价。
- 对学生步骤做公式解析和状态转移校验。
- 用大模型判断跳步、漏步、逻辑错误，再用规则做分数约束。

## 五、语文/英语主观题评分策略

英语作文维度：

| 维度 | 分值 |
| --- | ---: |
| 内容完整度 | 5 |
| 语法准确性 | 5 |
| 词汇丰富度 | 4 |
| 文章结构 | 4 |
| 拼写与标点 | 2 |

Demo 会识别以下典型问题：

- `I go to park`：过去时和冠词错误。
- `We play football`：过去时错误。
- `I very happy`：缺少 be 动词。

语文简答题维度：

- 审题立意；
- 内容完整度；
- 结构层次；
- 语言表达；
- 书写规范。

后续可升级为：

- 大模型按 Rubric 输出 JSON；
- 拼写/语法工具二次校验；
- 结合教师样例答案做语义相似度判断；
- 通过教师复核数据持续优化评分规则。

## 六、评语生成策略

评语遵循“三段式”：

1. 先肯定学生做得好的地方；
2. 再指出主要问题；
3. 最后给出具体改进建议。

Demo 版本根据评分结果、错误类型和薄弱点动态选择表达，不使用单一固定模板。例如：

- 数学满分：强调步骤清晰、计算准确，并建议挑战综合题。
- 数学部分正确：肯定方程思路，指出中间计算问题，建议代入检验。
- 英语作文：肯定内容表达，指出过去时、冠词、be 动词问题，给出仿写句型。

真实大模型接入时，可使用 `backend/app/prompts.py` 中的 Prompt，并要求模型输出严格 JSON。后端应增加 JSON Schema 校验，避免模型输出不可解析内容。

## 七、大模型 API 接入方案

`backend/app/services/llm.py` 已实现 OpenAI-compatible Chat Completions 客户端。开启方式：

```env
LLM_ENABLED=true
LLM_PROVIDER=kimi       # kimi | deepseek | custom
LLM_BASE_URL=https://api.moonshot.ai/v1
LLM_MODEL=kimi-k2.5
LLM_VISION_MODEL=kimi-k2.5
LLM_VISION_OCR=true
LLM_GRADE_FROM_IMAGE=true
KIMI_API_KEY=your_key_here
LLM_FALLBACK_TO_RULE=true
```

DeepSeek 示例：

```env
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_key_here
```

自定义兼容网关：

```env
LLM_ENABLED=true
LLM_PROVIDER=custom
LLM_BASE_URL=https://your-gateway.example.com/v1
LLM_MODEL=your-model
LLM_API_KEY=your_key_here
```

工作机制：

1. 先执行本地规则评分，得到稳定基准结果。
2. 若启用视觉 LLM，则先把上传图片发给视觉模型识别真实作答内容。
3. 批改时再次把图片、OCR 文本、题目、标准答案、满分、知识点和 Rubric 发送给模型。
4. 要求模型只返回 JSON。
5. 后端将模型 JSON 归一化到内部 `grading_results` 结构。
6. 如果模型请求失败或输出异常，默认回退本地规则评分；若 OCR 文本为空且无法调用视觉模型，则给 0 分并提示配置问题。

## 八、题库、班级、批量上传与二次标注

新增接口：

- `GET /api/question-bank`：题库列表。
- `POST /api/question-bank`：新增题库题目。
- `GET /api/classes`：班级列表。
- `POST /api/classes`：新增班级。
- `POST /api/bulk-upload`：批量创建提交，可自动 OCR 和批改。
- `POST /api/submissions/{id}/annotations`：教师二次标注。
- `GET /api/submissions/{id}/annotations`：查看标注记录。

二次标注用于沉淀教师纠偏数据：

- `label`：错误类型，例如“AI 评分偏高”“错因归因不准”。
- `comment`：教师说明。
- `corrected_score`：校正分数。

后续可将标注数据用于优化评分规则、构造 Few-shot 样例或微调数据。

## 九、鉴权、角色与多班级

Demo 默认不启用鉴权，方便评委直接体验。若设置：

```env
APP_API_TOKEN=your_demo_token
```

则上传、复核、题库新增、班级新增、批量上传、二次标注等写操作需要请求头：

```text
X-API-Key: your_demo_token
```

当前角色通过 `users.role` 区分 `student` 与 `teacher`，班级通过 `users.class_name` 和 `classrooms` 表管理。后续可扩展为 JWT 登录、RBAC 权限矩阵和多学校组织架构。

## 十、教师复核与 AI 安全边界

状态流转：

```text
待批改 -> AI 已批改 -> 教师已复核 -> 已返回学生
```

教师可执行：

- 查看 OCR 和 AI 批改详情；
- 修改分数；
- 修改评语；
- 添加复核备注；
- 返回学生。

该设计避免 AI 误判直接影响最终成绩，符合教学场景中“AI 辅助、教师确认”的产品原则。

## 十一、核心创新点

- 从“答案对错”升级为“过程诊断 + 部分分”。
- 多学科统一结构化批改输出。
- 知识点、错因、建议形成闭环。
- 教师复核数据可沉淀为后续模型优化样本。
- 班级报告能直接服务下一节课教学设计。
