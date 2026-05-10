# 希沃智评 —— 多学科 AI 智能作业批改系统

希沃智评是一个比赛级完整闭环 Demo，支持学生上传作业图片、真实/模拟 OCR 识别、多学科智能批改、过程分评分、个性化评语、知识点薄弱分析、教师复核和班级学情报告。

当前版本为了保证本地稳定演示，前端采用无构建 SPA，后端采用 FastAPI + SQLite。AI 与 OCR 能力都封装成独立服务层，后续可替换为 PaddleOCR、Mathpix、pix2tex 或大模型 API。

## 项目亮点

- 阶段一已完成固定 5 题数学试卷演示、稳定 OCR 结构化输出、稳定逐题批改、过程分与错因展示、教师复核、班级分析、评测中心、README 与演示流程。
- 支持上传包含完整题目与学生答题过程的整张未批改答题卡，由视觉大模型自动识别题目、学科、题型和学生答案并逐题批改。
- 数学不只判断答案对错，还分析解题步骤、错误位置和过程分。
- 英语/语文主观题按内容、结构、语言、语法/表达等维度评分。
- 每道题绑定知识点，错题自动归因到学生和班级薄弱知识点。
- 评语按学生表现动态生成，包含肯定、问题和具体建议。
- 教师可复核 AI 结果，修改分数与评语，并记录复核状态。
- 班级报告展示平均分、正确率、错题分布、高频薄弱点和教学建议。

## 页面说明

- 首页：教育科技感产品首屏，展示运行模式、AI 批改预览卡、三步演示流程、核心能力卡片和一键快速演示入口。
- 学生上传页：流程化步骤条、拖拽上传卡片、固定 5 题 Demo 说明和“快速演示：使用固定 5 题数学卷”按钮。
- 批改结果页：左侧原始作业图片，右侧总分卡、推荐讲解顺序、题目快速导航、逐题批改卡，并支持导出学生报告 Markdown 和批改 JSON。
- 教师工作台：状态筛选、提交列表、AI 与教师差异、整份复核、逐题复核表单和二次标注闭环说明。
- 班级分析页：仪表盘指标、各题正确率、薄弱知识点排行、高频错误和醒目的 AI 教学建议。
- 管理中心：题库、班级、批量上传、真实 OCR 测试、演示数据重置、教师二次标注和增强版评分准确率评测入口。

## 技术栈

- 前端：HTML + CSS + 原生 JavaScript SPA
- 后端：Python FastAPI
- 数据库：SQLite + SQLAlchemy
- 数据模型：Pydantic + SQLAlchemy ORM
- AI 模块：视觉大模型 OCR + OpenAI-compatible 大模型批改 + 规则兜底 + 知识点评测

## 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口与 REST API
│   │   ├── database.py          # SQLite 连接
│   │   ├── models.py            # 数据库模型
│   │   ├── schemas.py           # 请求模型
│   │   ├── seed.py              # 示例数据
│   │   ├── prompts.py           # AI 批改提示词
│   │   └── services/
│   │       ├── ocr.py           # OCR 接口层
│   │       ├── grading.py       # 智能批改规则
│   │       └── reports.py       # 学情统计报告
│   ├── data/                    # SQLite 数据库运行时生成
│   └── uploads/                 # 上传图片运行时保存
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── docs/
│   ├── TECHNICAL_DESIGN.md
│   └── DEMO_FLOW.md
└── requirements.txt
```

## 安装步骤

当前环境指定 Python：

```powershell
D:\anaconda3\envs\env\python.exe --version
```

如缺少依赖，安装：

```powershell
D:\anaconda3\envs\env\python.exe -m pip install -r requirements.txt
```

如需接入真实 OCR 或大模型，将 `.env.example` 复制为 `.env`，再填写对应密钥。不要把真实密钥提交到代码仓库。

```powershell
Copy-Item .env.example .env
```

常用配置示例：

```env
OCR_PROVIDER=llm
OCR_FALLBACK_TO_MOCK=false
ALLOW_MOCK_FOR_UPLOADED_IMAGES=false
DEMO_FIXED_MATH_PAPER_OCR=true
OCR_PREPROCESS_ENABLED=true
OCR_PREPROCESS_FOR_LLM=false
OCR_PREPROCESS_MAX_SIDE=1800
LLM_ENABLED=true
LLM_PROVIDER=kimi
LLM_BASE_URL=https://api.moonshot.ai/v1
LLM_MODEL=kimi-k2.5
LLM_VISION_MODEL=kimi-k2.5
LLM_VISION_OCR=true
LLM_GRADE_FROM_IMAGE=true
KIMI_API_KEY=your_key_here
```

如果只想用传统 OCR，也可以设置 `OCR_PROVIDER=paddle`、`baidu` 或 `tencent`。系统现在默认禁止真实上传图片静默使用 MockOCR，避免“任意图片都被当成样例答案而满分”。

## 运行模式

系统提供两种模式，首页和学生上传页会通过 `/api/runtime/status` 展示当前运行配置：

1. 稳定演示模式：保持 `DEMO_FIXED_MATH_PAPER_OCR=true`。点击“快速演示：使用固定 5 题数学卷”，或手动选择“自动识别 / 答题卡”并上传固定 5 题数学练习卷，系统会返回结构化 OCR 和稳定逐题批改结果：总分 `43 / 50`，第 3 题正确答案为 `62`，第 4 题显示为“部分正确”并得 `7 / 10`。这是比赛现场推荐模式。
2. 真实识别模式：设置 `DEMO_FIXED_MATH_PAPER_OCR=false`，再按需接入 `LLM 视觉 OCR`、`PaddleOCR`、百度 OCR、腾讯云 OCR、Mathpix、pix2tex 或 LaTeX-OCR，用于第二阶段验证任意答题卡泛化能力。

从稳定演示模式切换到真实识别模式，只需要修改项目根目录 `.env` 后重启后端：

```env
DEMO_FIXED_MATH_PAPER_OCR=false
```

上传真实图片时，系统会在进入传统 OCR 前执行图像预处理，包括灰度化、自动对比度增强、轻量去噪、自适应二值化和小角度倾斜矫正。视觉大模型默认使用原图；如现场图片偏暗或倾斜明显，可设置：

```env
OCR_PREPROCESS_FOR_LLM=true
```

如果日志出现 `HTTP 401: Invalid Authentication`，说明服务已经请求到 Kimi，但认证失败。请检查：

- `KIMI_API_KEY` 是否为新生成且完整的 key；
- key 前后不要有中文标点、空格或引号；
- `LLM_BASE_URL` 建议使用 `https://api.moonshot.ai/v1`；
- `LLM_VISION_MODEL` 建议使用当前官方视觉示例模型 `kimi-k2.5`；
- 修改 `.env` 后必须重启服务。

## 启动后端与前端

前端由 FastAPI 静态托管，启动一个服务即可：

```powershell
D:\anaconda3\envs\env\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

也可以运行内置脚本：

```powershell
scripts\run_demo.bat
```

浏览器访问：

```text
http://127.0.0.1:8000
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## API 接口说明

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/runtime/status` | 查看 OCR、预处理和大模型运行配置 |
| GET | `/api/evaluation/grading` | 运行内置评分准确率评测集 |
| POST | `/api/demo/reset` | 重置本地演示数据，清空测试提交并恢复默认演示样例 |
| GET | `/api/students` | 获取学生列表 |
| GET | `/api/assignments` | 获取作业列表 |
| GET | `/api/question-bank` | 获取题库列表 |
| POST | `/api/question-bank` | 新增题库题目 |
| GET | `/api/classes` | 获取班级列表 |
| POST | `/api/classes` | 新增班级 |
| POST | `/api/upload` | 上传作业图片，创建提交记录 |
| POST | `/api/bulk-upload` | 批量创建提交并可自动 OCR/批改 |
| POST | `/api/ocr` | 对提交执行 OCR 识别 |
| POST | `/api/grade` | 对 OCR 文本执行 AI 批改 |
| GET | `/api/submissions` | 获取提交列表 |
| GET | `/api/submissions/{id}` | 获取提交详情 |
| PUT | `/api/submissions/{id}/review` | 教师复核分数和评语 |
| GET | `/api/submissions/{id}/annotations` | 查看教师二次标注 |
| POST | `/api/submissions/{id}/annotations` | 新增教师二次标注 |
| GET | `/api/students/{id}/report` | 获取学生个人报告 |
| GET | `/api/classes/{class_name}/analysis` | 获取班级学情分析 |
| GET | `/api/classes/{class_name}/analysis/export` | 导出 Markdown 学情报告 |

## Demo 演示流程

1. 打开首页，看到“比赛稳定演示模式”和 AI 批改结果预览卡。
2. 点击“快速演示：使用固定 5 题数学卷”，系统会自动上传演示试卷、执行 OCR、逐题批改并跳转结果页。
3. 如需展示手动流程，也可以点击“进入 Demo”，选择学生、自动识别 / 答题卡并上传固定 5 题数学练习卷。
4. 系统展示 OCR 结构化识别结果。
5. 系统展示总分 `43 / 50`。
6. 在结果页使用“推荐讲解顺序”和“题目快速导航”定位重点题。
7. 重点展示第 3 题计算错误：`90 - 28 = 72`，正确应为 `62`。
8. 重点展示第 4 题过程正确但最终答案错误：前两步正确，最后 `x = 4` 错误，系统给部分分 `7 / 10`。
9. 展示逐题批改卡片、知识点薄弱分析和个性化建议，并导出学生报告 Markdown 或 AI 批改 JSON。
10. 进入教师工作台。
11. 教师查看 AI 批改结果、AI 原始分数和教师复核分数差异。
12. 展示逐题复核：第 3 题可把教师分数改为 `5 / 10`，填写“退位减法错误较明显，扣分应更严格”，并加入标注样本。
13. 教师复核整份作业分数和评语，保存复核。
14. 进入班级分析页。
15. 查看平均分、正确率、薄弱点排行、高频错误和 AI 教学建议。
16. 点击“导出报告”，下载班级学情分析 Markdown 文件。
17. 进入管理中心或评测中心。
18. 展示增强版评分评测：测试样例数、平均分差、评分误差合格率、错因识别准确率、知识点识别准确率、过程分合理率、教师复核一致率和评语完整率。
19. 如需验证真实能力，在管理中心打开“真实 OCR 测试”，上传真实试卷，只看 OCR 状态、题目数、文本长度和耗时。
20. 比赛前可点击“重置演示数据”，恢复干净演示环境。
21. 结束时总结亮点：整卷识别、逐题过程分、错因定位、逐题教师复核、评测依据、真实 OCR 可验证入口和班级报告。

## 答辩亮点

- 不是简单判对错，而是能逐题分析过程并给部分分。
- 第 3 题展示计算错误定位，第 4 题展示“过程正确但最终答案错误”的过程分能力。
- 评测中心用内置样例对比分数、错因和知识点，能解释准确率依据。
- 教师复核避免 AI 误判直接影响成绩，逐题复核结果可作为二次标注数据。
- 班级分析把单次批改转化为可执行的教学建议。
- 稳定演示模式保证 3 到 5 分钟比赛流程完整可复现。

## 内置示例数据

- 学生：张三、李四、王五，均属于七年级一班。
- 自动识别答题卡：用于任意整张未批改答题卡批改，不依赖题库标准答案。
- 数学题：解方程 `2x + 3 = 7`，标准答案 `x = 2`。
- 英语作文：`Write a short passage about your weekend.`
- 英语样例作文：`I go to park with my friend. We play football. I very happy.`

## 后续优化方向

- 已预留并实现 OCR Provider：`mock`、`paddle`、`baidu`、`tencent`、`llm`。
- 已增加真实图片预处理：灰度化、对比度增强、去噪、二值化、倾斜矫正，并在 OCR 结果中给出诊断提示。
- 已预留并实现公式 OCR Provider：`mock`、`mathpix`、`pix2tex`、`latex-ocr`。
- 已实现 OpenAI-compatible 大模型评分适配，可配置 Kimi、DeepSeek 或自定义网关。
- 已增加题库管理、班级管理、批量上传和教师二次标注接口及管理页。
- 班级分析页支持 ECharts CDN，可视化失败时保留 CSS 图表兜底。
- 已增加内置评分评测接口、单元测试样例、可选 API Token 鉴权、多班级基础模型。
