const app = document.querySelector("#app");

const state = {
  students: [],
  assignments: [],
  classes: [],
  submissions: [],
  evaluation: null,
  selectedFile: null,
  selectedPreview: "",
  lastSubmissionId: null,
};

document.addEventListener("DOMContentLoaded", init);
window.addEventListener("hashchange", renderRoute);

async function init() {
  await loadBaseData();
  if (!location.hash) location.hash = "#home";
  renderRoute();
}

async function loadBaseData() {
  const [students, assignments, classes] = await Promise.all([
    api("/api/students"),
    api("/api/assignments"),
    api("/api/classes"),
  ]);
  state.students = students.data;
  state.assignments = assignments.data;
  state.classes = classes.data;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail || "请求失败");
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

function renderRoute() {
  const hash = location.hash.replace("#", "") || "home";
  const [view, id] = hash.split("/");
  setActiveNav(view);
  if (view === "student") return renderStudent();
  if (view === "result") return renderResult(id || state.lastSubmissionId);
  if (view === "teacher") return renderTeacher(id);
  if (view === "analysis") return renderAnalysis();
  if (view === "management") return renderManagementPage();
  renderHome();
}

function setActiveNav(view) {
  document.querySelectorAll("[data-nav]").forEach((item) => {
    item.classList.toggle("active", item.dataset.nav === view);
  });
}

function renderHome() {
  app.innerHTML = `
    <section class="hero">
      <div class="hero-copy">
        <span class="feature-tag">多学科 AI 智能作业批改系统</span>
        <h1>希沃智评</h1>
        <p>面向学生和教师的作业批改 Demo，覆盖图片上传、模拟 OCR、数学过程分、英语/语文主观题评价、个性化评语、知识点薄弱分析和班级学情报告。</p>
        <div class="hero-actions">
          <a class="btn" href="#student">进入 Demo</a>
          <a class="btn secondary" href="#teacher">教师工作台</a>
        </div>
      </div>
      <div class="hero-visual" aria-label="智能批改示意">
        <div class="paper-stack">
          <div class="tag-list">
            <span class="tag">OCR</span>
            <span class="tag">过程分</span>
            <span class="tag">错因归因</span>
          </div>
          <div class="paper-lines">
            <div class="paper-line"></div>
            <div class="paper-line mid"></div>
            <div class="paper-line"></div>
            <div class="paper-line short"></div>
            <div class="paper-line mid"></div>
          </div>
          <div class="score-badge">AI 评</div>
        </div>
      </div>
    </section>
    <section>
      <div class="section-head">
        <div>
          <h2>核心能力</h2>
          <p>比赛 Demo 重点突出智能批改、个性化评语和学情分析。</p>
        </div>
      </div>
      <div class="feature-grid">
        ${featureCard("作业图片上传", "支持 jpg、png、jpeg，上传后展示预览并创建提交记录。")}
        ${featureCard("模拟 OCR 接口", "保留可替换接口，后续可接 PaddleOCR、Mathpix 或云 OCR。")}
        ${featureCard("过程化评分", "数学按思路、方法、计算、答案拆分给分，支持部分分。")}
        ${featureCard("班级学情报告", "统计平均分、正确率、错题分布和高频薄弱知识点。")}
      </div>
    </section>
  `;
}

function featureCard(title, text) {
  return `<article class="feature-card"><h3>${title}</h3><p>${text}</p></article>`;
}

function renderStudent() {
  const defaultStudent = state.students[0]?.id || "";
  const subjects = unique(state.assignments.map((item) => item.subject));
  const defaultSubject = subjects.includes("自动识别") ? "自动识别" : (subjects[0] || "数学");
  const types = getTypes(defaultSubject);
  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>学生上传</h2>
          <p>上传包含完整题目和学生作答的未批改答题卡，系统会自动识别题目、题型、学科并逐题批改。</p>
        </div>
        <a class="btn ghost" href="#teacher">查看教师端</a>
      </div>
      <div class="upload-grid">
        <form id="uploadForm" class="panel form-grid">
          <div class="field">
            <label for="studentSelect">学生</label>
            <select id="studentSelect">${state.students.map((student) => `<option value="${student.id}" ${student.id === defaultStudent ? "selected" : ""}>${student.name} · ${student.class_name}</option>`).join("")}</select>
          </div>
          <div class="field">
            <label for="subjectSelect">学科 / 模式</label>
            <select id="subjectSelect">${subjects.map((subject) => `<option value="${subject}" ${subject === defaultSubject ? "selected" : ""}>${subject}</option>`).join("")}</select>
          </div>
          <div class="field">
            <label for="typeSelect">题型</label>
            <select id="typeSelect">${types.map((type) => `<option value="${type}">${type}</option>`).join("")}</select>
          </div>
          <div id="assignmentInfo" class="card">${assignmentInfo(defaultSubject, types[0])}</div>
          <div class="field">
            <label for="imageInput">作业图片</label>
            <div class="upload-drop">
              <input id="imageInput" type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" />
              <div id="previewWrap">${state.selectedPreview ? `<img class="preview" src="${state.selectedPreview}" alt="作业预览" />` : `<span>jpg / png / jpeg</span>`}</div>
            </div>
          </div>
          <div class="button-row">
            <button id="gradeBtn" class="btn" type="submit">开始 AI 批改</button>
            <span id="uploadStatus" class="muted"></span>
          </div>
        </form>
        <aside class="panel">
          <h3>Demo 内置样例</h3>
          <div class="bar-list">
            <div class="card">
              <strong>数学计算题</strong>
              <p class="muted">解方程 2x + 3 = 7，输出过程分、错误位置和正确解法。</p>
            </div>
            <div class="card">
              <strong>英语作文</strong>
              <p class="muted">识别一般过去时、冠词、be 动词和句子结构问题。</p>
            </div>
            <div class="card">
              <strong>教师复核</strong>
              <p class="muted">教师可修改分数和评语，提交后记录复核状态。</p>
            </div>
          </div>
        </aside>
      </div>
    </section>
  `;

  const subjectSelect = document.querySelector("#subjectSelect");
  const typeSelect = document.querySelector("#typeSelect");
  const imageInput = document.querySelector("#imageInput");
  const uploadForm = document.querySelector("#uploadForm");

  subjectSelect.addEventListener("change", () => {
    const nextTypes = getTypes(subjectSelect.value);
    typeSelect.innerHTML = nextTypes.map((type) => `<option value="${type}">${type}</option>`).join("");
    document.querySelector("#assignmentInfo").innerHTML = assignmentInfo(subjectSelect.value, typeSelect.value);
  });
  typeSelect.addEventListener("change", () => {
    document.querySelector("#assignmentInfo").innerHTML = assignmentInfo(subjectSelect.value, typeSelect.value);
  });
  imageInput.addEventListener("change", handlePreview);
  uploadForm.addEventListener("submit", handleGradeSubmit);
}

function assignmentInfo(subject, type) {
  const assignment = findAssignment(subject, type);
  if (!assignment) return `<p class="muted">暂无匹配作业</p>`;
  return `
    <h3>${escapeHtml(assignment.title)}</h3>
    <p class="muted">${escapeHtml(assignment.question)}</p>
    <div class="tag-list">${assignment.knowledge_points.map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("")}</div>
  `;
}

function handlePreview(event) {
  const file = event.target.files[0];
  state.selectedFile = file || null;
  if (!file) {
    state.selectedPreview = "";
    document.querySelector("#previewWrap").innerHTML = "<span>jpg / png / jpeg</span>";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.selectedPreview = reader.result;
    document.querySelector("#previewWrap").innerHTML = `<img class="preview" src="${state.selectedPreview}" alt="作业预览" />`;
  };
  reader.readAsDataURL(file);
}

async function handleGradeSubmit(event) {
  event.preventDefault();
  const button = document.querySelector("#gradeBtn");
  const status = document.querySelector("#uploadStatus");
  const subject = document.querySelector("#subjectSelect").value;
  const questionType = document.querySelector("#typeSelect").value;
  const assignment = findAssignment(subject, questionType);
  const studentId = Number(document.querySelector("#studentSelect").value);

  button.disabled = true;
  status.textContent = "上传中...";
  try {
    const imageData = state.selectedFile ? await readFileAsDataURL(state.selectedFile) : "";
    const upload = await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({
        student_id: studentId,
        subject,
        question_type: questionType,
        assignment_id: assignment?.id,
        image_name: state.selectedFile?.name || `mock-${subject}.png`,
        image_data: imageData,
      }),
    });
    status.textContent = "OCR 识别中...";
    const submissionId = upload.data.submission_id;
    await api("/api/ocr", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId }),
    });
    status.textContent = "AI 批改中...";
    await api("/api/grade", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId, subject, question_type: questionType }),
    });
    state.lastSubmissionId = submissionId;
    showToast("批改完成");
    location.hash = `#result/${submissionId}`;
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    status.textContent = "";
  }
}

async function renderResult(submissionId) {
  if (!submissionId) {
    app.innerHTML = `<div class="empty">暂无批改结果</div>`;
    return;
  }
  try {
    const detail = await api(`/api/submissions/${submissionId}`);
    const submission = detail.data;
    const report = await api(`/api/students/${submission.student.id}/report`);
    app.innerHTML = `
      <section>
        <div class="section-head">
          <div>
            <h2>批改结果</h2>
            <p>${escapeHtml(submission.student.name)} · ${escapeHtml(submission.assignment.title)}</p>
          </div>
          <div class="button-row">
            <button id="regradeCurrent" class="btn" type="button" data-submission-id="${submission.id}">重新识别并批改</button>
            <a class="btn secondary" href="#student">继续上传</a>
            <a class="btn ghost" href="#teacher/${submission.id}">教师复核</a>
          </div>
        </div>
        <div class="result-grid">
          <aside class="panel">
            ${scorePanel(submission)}
            <h3>OCR 识别结果</h3>
            ${engineInfo(submission)}
            <div class="ocr-box">${escapeHtml(submission.ocr_text || "暂无 OCR 内容")}</div>
            ${submission.image_url ? `<h3>图片预览</h3><img class="preview" src="${submission.image_url}" alt="作业图片" />` : ""}
          </aside>
          <div class="panel">
            ${gradingDetail(submission)}
          </div>
        </div>
        <div class="panel" style="margin-top:18px">
          <h3>个人薄弱点</h3>
          ${weakPointList(report.data.weak_points)}
          <p class="muted">${escapeHtml(report.data.personal_suggestion)}</p>
        </div>
      </section>
    `;
    document.querySelector("#regradeCurrent")?.addEventListener("click", rerunCurrentSubmission);
  } catch (error) {
    app.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function rerunCurrentSubmission(event) {
  const button = event.currentTarget;
  const submissionId = button.dataset.submissionId;
  button.disabled = true;
  button.textContent = "识别中...";
  try {
    await api("/api/ocr", {
      method: "POST",
      body: JSON.stringify({ submission_id: Number(submissionId) }),
    });
    button.textContent = "批改中...";
    await api("/api/grade", {
      method: "POST",
      body: JSON.stringify({ submission_id: Number(submissionId) }),
    });
    showToast("已重新批改");
    await renderResult(submissionId);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "重新识别并批改";
  }
}

function scorePanel(submission) {
  const score = submission.effective_score ?? submission.ai_score ?? 0;
  const full = submission.grading_result?.full_score ?? submission.assignment.full_score;
  const statusClass = statusClassName(submission.status);
  return `
    <div class="score-panel">
      <span class="status ${statusClass}">${escapeHtml(submission.status)}</span>
      <div class="score">${score}<small> / ${full}</small></div>
      <strong>${submission.grading_result?.is_correct ? "答案正确" : "需要订正"}</strong>
    </div>
  `;
}

function gradingDetail(submission) {
  const result = submission.grading_result || {};
  const isComposition = submission.subject === "英语" || submission.subject === "语文";
  const sheet = result.ai_metadata?.answer_sheet || {};
  return `
    <div class="tag-list" style="margin-bottom:14px">
      <span class="tag">AI 引擎：${escapeHtml(result.ai_engine || "RuleEngine")}</span>
      ${sheet.fallback ? `<span class="tag">OCR 文本兜底</span>` : ""}
      ${Array.isArray(sheet.questions) && sheet.questions.length ? `<span class="tag">逐题：${sheet.questions.length} 题</span>` : ""}
    </div>
    <h3>评分维度</h3>
    ${dimensionBars(result.dimension_scores || {}, submission.assignment.full_score)}
    ${answerSheetDetails(result)}
    <h3>${isComposition ? "内容与表达分析" : "解题过程分析"}</h3>
    <p class="muted">${escapeHtml(result.process_analysis || result.content_analysis || "暂无分析")}</p>
    ${result.structure_analysis ? `<p class="muted">${escapeHtml(result.structure_analysis)}</p>` : ""}
    ${result.language_analysis ? `<p class="muted">${escapeHtml(result.language_analysis)}</p>` : ""}
    ${mistakeBlock(result)}
    ${result.correct_solution ? `<h3>正确解法</h3><div class="code-box">${escapeHtml(result.correct_solution)}</div>` : ""}
    ${result.revised_example ? `<h3>修改示例</h3><div class="code-box">${escapeHtml(result.revised_example)}</div>` : ""}
    <h3>知识点</h3>
    <div class="tag-list">${(result.knowledge_points || []).map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("") || "<span class='muted'>暂无</span>"}</div>
    <h3>薄弱点</h3>
    <div class="tag-list">${(result.weak_points || []).map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("") || "<span class='muted'>暂无明显薄弱点</span>"}</div>
    <h3>个性化评语</h3>
    <p class="muted">${escapeHtml(result.comment || "暂无评语")}</p>
    <h3>学习建议</h3>
    <p class="muted">${escapeHtml(result.suggestion || "暂无建议")}</p>
  `;
}

function answerSheetDetails(result) {
  const sheet = result.ai_metadata?.answer_sheet;
  const questions = Array.isArray(sheet?.questions) ? sheet.questions : [];
  if (!questions.length) return "";
  const correctCount = questions.filter((question) => question.is_correct).length;
  const totalScore = sheet?.score ?? result.score ?? 0;
  const totalFull = sheet?.full_score ?? result.full_score ?? 0;
  return `
    <h3>逐题批改</h3>
    <div class="mini-grid">
      <div class="metric-card"><span>题目数</span><strong>${questions.length}</strong></div>
      <div class="metric-card"><span>正确题</span><strong>${correctCount}</strong></div>
      <div class="metric-card"><span>需订正</span><strong>${questions.length - correctCount}</strong></div>
      <div class="metric-card"><span>整卷得分</span><strong>${escapeHtml(totalScore)} / ${escapeHtml(totalFull)}</strong></div>
    </div>
    <div class="bar-list">
      ${questions.map((question, index) => {
        const no = question.question_no || index + 1;
        const score = question.score ?? 0;
        const full = question.full_score ?? "-";
        const mistakes = Array.isArray(question.mistakes) ? question.mistakes : [];
        return `
          <div class="card question-card ${question.is_correct ? "is-correct" : "needs-review"}">
            <div class="section-head" style="margin-bottom:10px">
              <div>
                <strong>第 ${escapeHtml(no)} 题 · ${escapeHtml(question.subject || "自动识别")} · ${escapeHtml(question.question_type || "题型未定")}</strong>
                <p class="muted">${escapeHtml(question.question_text || "未识别到完整题干")}</p>
              </div>
              <span class="score-pill ${question.is_correct ? "ok" : "bad"}">${question.is_correct ? "正确" : "订正"} · ${escapeHtml(score)} / ${escapeHtml(full)}</span>
            </div>
            <p class="muted"><strong>学生作答：</strong>${escapeHtml(question.student_answer || "未识别到作答")}</p>
            <p class="muted"><strong>分析：</strong>${escapeHtml(question.process_analysis || question.comment || "暂无分析")}</p>
            ${mistakes.length ? `<div class="bar-list">${mistakes.map((item) => `<p class="muted"><strong>${escapeHtml(item.step || "问题")}：</strong>${escapeHtml(item.error || item.reason || item)}</p>`).join("")}</div>` : ""}
            ${question.correct_solution ? `<div class="code-box">${escapeHtml(question.correct_solution)}</div>` : ""}
            ${question.suggestion ? `<p class="muted"><strong>建议：</strong>${escapeHtml(question.suggestion)}</p>` : ""}
            <div class="tag-list" style="margin-top:10px">
              ${(question.knowledge_points || []).map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("")}
              ${(question.weak_points || []).map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("")}
            </div>
          </div>
        `;
      }).join("")}
    </div>
    ${sheet.warnings?.length ? `<h3>整卷识别提示</h3><div class="card">${sheet.warnings.map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}</div>` : ""}
  `;
}

function engineInfo(submission) {
  const warnings = submission.ocr_warnings || [];
  return `
    <div class="tag-list" style="margin-bottom:12px">
      <span class="tag">OCR：${escapeHtml(submission.ocr_engine || "未执行")}</span>
      ${submission.ocr_confidence == null ? "" : `<span class="tag">置信度：${Number(submission.ocr_confidence).toFixed(2)}</span>`}
    </div>
    ${warnings.length ? `<div class="card" style="margin-bottom:12px"><strong>识别提示</strong>${warnings.map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}</div>` : ""}
  `;
}

function mistakeBlock(result) {
  const items = [...(result.mistakes || []), ...(result.errors || [])];
  if (!items.length) return `<h3>错误原因</h3><p class="muted">未发现明显错误。</p>`;
  return `
    <h3>错误原因</h3>
    <div class="bar-list">
      ${items
        .map(
          (item) => `
            <div class="card">
              <strong>${escapeHtml(item.step || item.original || "问题")}</strong>
              <p class="muted">${escapeHtml(item.error || item.reason || "")}</p>
              ${item.suggestion ? `<p class="muted">建议：${escapeHtml(item.suggestion)}</p>` : ""}
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function dimensionBars(scores, fullScore) {
  const entries = Object.entries(scores).filter(([key]) => key !== "总分" && key !== "满分");
  if (!entries.length) return `<p class="muted">暂无维度分。</p>`;
  const max = Math.max(...entries.map(([, value]) => Number(value) || 0), fullScore / entries.length, 1);
  return `
    <div class="bar-list">
      ${entries
        .map(([key, value]) => {
          const width = Math.min(100, Math.round(((Number(value) || 0) / max) * 100));
          return `
            <div class="bar-row">
              <div class="bar-meta"><span>${escapeHtml(key)}</span><strong>${value}</strong></div>
              <div class="bar-track"><div class="bar-fill" style="--width:${width}%"></div></div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

async function renderTeacher(selectedId) {
  const response = await api("/api/submissions");
  state.submissions = response.data;
  const selected = selectedId || state.submissions[0]?.id;
  const detail = selected ? (await api(`/api/submissions/${selected}`)).data : null;

  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>教师工作台</h2>
          <p>查看 AI 批改结果，进行确认、调整或返回学生。</p>
        </div>
        <a class="btn secondary" href="#analysis">班级分析</a>
      </div>
      <div class="teacher-layout">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>学生</th>
                <th>学科</th>
                <th>题型</th>
                <th>状态</th>
                <th>分数</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${state.submissions.map(submissionRow).join("")}
            </tbody>
          </table>
        </div>
        ${detail ? reviewPanel(detail) : `<div class="empty">暂无提交记录</div>`}
      </div>
    </section>
  `;

  document.querySelectorAll("[data-open-submission]").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#teacher/${button.dataset.openSubmission}`;
    });
  });

  const reviewForm = document.querySelector("#reviewForm");
  if (reviewForm) reviewForm.addEventListener("submit", handleReviewSubmit);
  const returnBtn = document.querySelector("#returnBtn");
  if (returnBtn) returnBtn.addEventListener("click", handleReturnSubmit);
}

function submissionRow(submission) {
  const score = submission.effective_score ?? "-";
  const full = submission.assignment.full_score;
  return `
    <tr>
      <td>${escapeHtml(submission.student.name)}</td>
      <td>${escapeHtml(submission.subject)}</td>
      <td>${escapeHtml(submission.question_type)}</td>
      <td><span class="status ${statusClassName(submission.status)}">${escapeHtml(submission.status)}</span></td>
      <td>${score === "-" ? "-" : `${score}/${full}`}</td>
      <td><button class="btn ghost" type="button" data-open-submission="${submission.id}">查看详情</button></td>
    </tr>
  `;
}

function reviewPanel(submission) {
  const result = submission.grading_result || {};
  return `
    <div class="review-grid">
      <div class="panel">
        <h3>${escapeHtml(submission.student.name)} · ${escapeHtml(submission.assignment.title)}</h3>
        ${scorePanel(submission)}
        ${gradingDetail(submission)}
      </div>
      <form id="reviewForm" class="panel form-grid" data-submission-id="${submission.id}">
        <h3>教师复核</h3>
        <div class="field">
          <label for="teacherScore">教师分数</label>
          <input id="teacherScore" name="teacher_score" type="number" min="0" max="${submission.assignment.full_score}" step="0.5" value="${submission.teacher_score ?? submission.ai_score ?? 0}" />
        </div>
        <div class="field">
          <label for="teacherComment">评语</label>
          <textarea id="teacherComment" name="comment">${escapeHtml(result.comment || "")}</textarea>
        </div>
        <div class="field">
          <label for="reviewNote">复核备注</label>
          <textarea id="reviewNote" name="review_note">${escapeHtml(result.review_note || "")}</textarea>
        </div>
        <div class="button-row">
          <button class="btn" type="submit">确认复核</button>
          <button id="returnBtn" class="btn warn" type="button" data-submission-id="${submission.id}">返回学生</button>
        </div>
      </form>
    </div>
  `;
}

async function handleReviewSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.dataset.submissionId;
  await submitReview(id, "confirm");
}

async function handleReturnSubmit(event) {
  const id = event.currentTarget.dataset.submissionId;
  await submitReview(id, "return");
}

async function submitReview(id, action) {
  const teacherScore = Number(document.querySelector("#teacherScore").value);
  const comment = document.querySelector("#teacherComment").value;
  const reviewNote = document.querySelector("#reviewNote").value;
  try {
    await api(`/api/submissions/${id}/review`, {
      method: "PUT",
      body: JSON.stringify({
        teacher_score: teacherScore,
        comment,
        review_note: reviewNote,
        action,
      }),
    });
    showToast(action === "return" ? "已返回学生" : "复核已保存");
    await renderTeacher(id);
  } catch (error) {
    showToast(error.message);
  }
}

async function renderAnalysis() {
  const response = await api(`/api/classes/${encodeURIComponent("七年级一班")}/analysis`);
  const data = response.data;
  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>班级分析</h2>
          <p>${escapeHtml(data.class_name)} · ${data.total_submissions} 份提交</p>
        </div>
        <button id="exportBtn" class="btn" type="button">导出报告</button>
      </div>
      <div class="metric-grid">
        ${metricCard("平均分", data.average_score)}
        ${metricCard("正确率", data.accuracy_rate)}
        ${metricCard("最高分", data.highest_score)}
        ${metricCard("最低分", data.lowest_score)}
      </div>
      <div class="analysis-grid" style="margin-top:18px">
        <div class="panel">
          <h3>薄弱知识点排行</h3>
          ${rankBars(data.common_weak_points, "knowledge_point", "count")}
          <h3>教学建议</h3>
          <p class="muted">${escapeHtml(data.teacher_suggestion)}</p>
        </div>
        <div class="panel">
          <h3>各题正确率</h3>
          ${accuracyBars(data.question_accuracy)}
          <h3>高频错误</h3>
          ${mistakeRank(data.frequent_mistakes)}
        </div>
      </div>
    </section>
  `;
  document.querySelector("#exportBtn").addEventListener("click", exportClassReport);
  renderECharts(data);
}

function renderECharts(data) {
  if (!window.echarts) return;
  const weakPanel = document.querySelector(".analysis-grid .panel");
  const accuracyPanel = document.querySelectorAll(".analysis-grid .panel")[1];
  if (!weakPanel || !accuracyPanel) return;
  const weakChart = document.createElement("div");
  weakChart.className = "chart-box";
  weakChart.style.height = "260px";
  weakPanel.insertBefore(weakChart, weakPanel.children[1] || null);
  const accuracyChart = document.createElement("div");
  accuracyChart.className = "chart-box";
  accuracyChart.style.height = "260px";
  accuracyPanel.insertBefore(accuracyChart, accuracyPanel.children[1] || null);

  echarts.init(weakChart).setOption({
    tooltip: {},
    grid: { left: 24, right: 18, top: 28, bottom: 36, containLabel: true },
    xAxis: { type: "category", data: data.common_weak_points.map((item) => item.knowledge_point) },
    yAxis: { type: "value", minInterval: 1 },
    series: [{ type: "bar", data: data.common_weak_points.map((item) => item.count), itemStyle: { color: "#246bfe" } }],
  });

  echarts.init(accuracyChart).setOption({
    tooltip: { formatter: "{b}: {c}%" },
    grid: { left: 24, right: 18, top: 28, bottom: 36, containLabel: true },
    xAxis: { type: "category", data: data.question_accuracy.map((item) => item.question) },
    yAxis: { type: "value", max: 100 },
    series: [{ type: "line", smooth: true, data: data.question_accuracy.map((item) => item.accuracy), areaStyle: {}, itemStyle: { color: "#7657ff" } }],
  });
}

function metricCard(label, value) {
  return `<div class="metric-card"><span class="muted">${label}</span><div class="score" style="font-size:34px">${value}</div></div>`;
}

function rankBars(items, labelKey, valueKey) {
  if (!items.length) return `<p class="muted">暂无数据</p>`;
  const max = Math.max(...items.map((item) => item[valueKey]), 1);
  return `
    <div class="bar-list">
      ${items
        .map((item) => {
          const width = Math.round((item[valueKey] / max) * 100);
          return `
            <div class="bar-row">
              <div class="bar-meta"><span>${escapeHtml(item[labelKey])}</span><strong>${item[valueKey]}</strong></div>
              <div class="bar-track"><div class="bar-fill" style="--width:${width}%"></div></div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function accuracyBars(items) {
  if (!items.length) return `<p class="muted">暂无数据</p>`;
  return `
    <div class="bar-list">
      ${items
        .map(
          (item) => `
            <div class="bar-row">
              <div class="bar-meta"><span>${escapeHtml(item.question)}</span><strong>${item.accuracy}%</strong></div>
              <div class="bar-track"><div class="bar-fill" style="--width:${item.accuracy}%"></div></div>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function mistakeRank(items) {
  if (!items.length) return `<p class="muted">暂无高频错误</p>`;
  return `<div class="bar-list">${items.map((item) => `<div class="card"><strong>${escapeHtml(item.mistake)}</strong><p class="muted">出现 ${item.count} 次</p></div>`).join("")}</div>`;
}

async function exportClassReport() {
  try {
    const text = await api(`/api/classes/${encodeURIComponent("七年级一班")}/analysis/export`);
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "七年级一班-学情分析报告.md";
    anchor.click();
    URL.revokeObjectURL(url);
    showToast("报告已生成");
  } catch (error) {
    showToast(error.message);
  }
}

function weakPointList(items) {
  if (!items.length) return `<p class="muted">暂无明显薄弱知识点。</p>`;
  return `
    <div class="bar-list">
      ${items
        .map(
          (item) => `
            <div class="card">
              <strong>${escapeHtml(item.knowledge_point)} · ${escapeHtml(item.mastery_level)}</strong>
              <p class="muted">错误次数：${item.error_count}</p>
              <p class="muted">${escapeHtml(item.suggestion)}</p>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderManagement() {
  const firstAssignment = state.assignments[0];
  const teacher = state.students.find((item) => item.role === "teacher");
  const evaluation = state.evaluation;
  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>管理中心</h2>
          <p>题库管理、班级管理、批量上传和教师二次标注的扩展入口。</p>
        </div>
        <button id="refreshManagement" class="btn ghost" type="button">刷新数据</button>
      </div>
      <div class="analysis-grid">
        <form id="questionForm" class="panel form-grid">
          <h3>新增题库题目</h3>
          <div class="field"><label>标题</label><input name="title" value="分数方程拓展练习" /></div>
          <div class="field"><label>学科</label><select name="subject"><option>数学</option><option>英语</option><option>语文</option></select></div>
          <div class="field"><label>题型</label><select name="question_type"><option>计算题</option><option>应用题</option><option>作文</option><option>简答题</option></select></div>
          <div class="field"><label>题目</label><textarea name="question">解方程 x / 2 + 1 = 4，求 x。</textarea></div>
          <div class="field"><label>标准答案</label><input name="standard_answer" value="x = 6" /></div>
          <div class="field"><label>满分</label><input name="full_score" type="number" value="10" /></div>
          <div class="field"><label>知识点，逗号分隔</label><input name="knowledge_points" value="一元一次方程,分数运算,等式性质" /></div>
          <button class="btn" type="submit">加入题库</button>
        </form>
        <form id="classForm" class="panel form-grid">
          <h3>新增班级</h3>
          <div class="field"><label>班级名称</label><input name="name" value="七年级二班" /></div>
          <div class="field"><label>年级</label><input name="grade" value="七年级" /></div>
          <div class="field"><label>教师</label><input name="teacher_name" value="陈老师" /></div>
          <button class="btn" type="submit">创建班级</button>
        </form>
      </div>
      <div class="analysis-grid" style="margin-top:18px">
        <form id="bulkForm" class="panel form-grid">
          <h3>批量上传 Demo</h3>
          <p class="muted">选择一个题目后，将为当前三个学生批量创建提交并自动 OCR + 批改。</p>
          <div class="field">
            <label>作业</label>
            <select name="assignment_id">
              ${state.assignments.map((item) => `<option value="${item.id}" ${firstAssignment?.id === item.id ? "selected" : ""}>${escapeHtml(item.title)} · ${escapeHtml(item.subject)}</option>`).join("")}
            </select>
          </div>
          <button class="btn" type="submit">批量生成提交</button>
        </form>
        <div class="panel">
          <h3>评分准确率评测</h3>
          ${evaluation ? evaluationPanel(evaluation) : `<p class="muted">暂无评测数据</p>`}
        </div>
      </div>
      <div class="analysis-grid" style="margin-top:18px">
        <form id="annotationForm" class="panel form-grid">
          <h3>教师二次标注</h3>
          <p class="muted">将教师复核沉淀为训练样本，后续可用于优化评分规则和模型提示词。</p>
          <div class="field">
            <label>提交记录</label>
            <select name="submission_id">
              ${state.submissions.map((item) => `<option value="${item.id}">${escapeHtml(item.student.name)} · ${escapeHtml(item.assignment.title)}</option>`).join("")}
            </select>
          </div>
          <div class="field"><label>标注标签</label><input name="label" value="AI 评分偏高" /></div>
          <div class="field"><label>标注说明</label><textarea name="comment">中间步骤缺失，建议扣除 1 分过程分。</textarea></div>
          <div class="field"><label>校正分数</label><input name="corrected_score" type="number" step="0.5" value="9" /></div>
          <input type="hidden" name="teacher_id" value="${teacher?.id || ""}" />
          <button class="btn" type="submit">保存标注</button>
        </form>
        <div class="panel">
          <h3>题库列表</h3>
          <div class="table-wrap">
            <table>
              <thead><tr><th>题目</th><th>学科</th><th>题型</th><th>知识点</th></tr></thead>
              <tbody>${state.assignments.map((item) => `<tr><td>${escapeHtml(item.title)}</td><td>${escapeHtml(item.subject)}</td><td>${escapeHtml(item.question_type)}</td><td>${(item.knowledge_points || []).map(escapeHtml).join("、")}</td></tr>`).join("")}</tbody>
            </table>
          </div>
        </div>
        <div class="panel">
          <h3>班级列表</h3>
          <div class="table-wrap">
            <table>
              <thead><tr><th>班级</th><th>年级</th><th>教师</th></tr></thead>
              <tbody>${state.classes.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.grade || "")}</td><td>${escapeHtml(item.teacher_name || "")}</td></tr>`).join("")}</tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  `;
  document.querySelector("#refreshManagement").addEventListener("click", async () => {
    await refreshManagementData();
    renderManagement();
  });
  document.querySelector("#questionForm").addEventListener("submit", handleCreateQuestion);
  document.querySelector("#classForm").addEventListener("submit", handleCreateClass);
  document.querySelector("#bulkForm").addEventListener("submit", handleBulkUpload);
  document.querySelector("#annotationForm").addEventListener("submit", handleAnnotation);
}

function evaluationPanel(evaluation) {
  const summary = evaluation.summary || {};
  const cases = evaluation.cases || [];
  return `
    <div class="mini-grid">
      <div class="metric-card"><span>样例数</span><strong>${summary.total_cases ?? 0}</strong></div>
      <div class="metric-card"><span>通过率</span><strong>${percent(summary.pass_rate)}</strong></div>
      <div class="metric-card"><span>错题识别</span><strong>${percent(summary.wrong_question_accuracy)}</strong></div>
      <div class="metric-card"><span>平均误差</span><strong>${summary.average_score_error ?? 0}</strong></div>
    </div>
    <div class="bar-list" style="margin-top:12px">
      ${cases.map((item) => `
        <div class="eval-row">
          <div>
            <strong>${escapeHtml(item.name)}</strong>
            <p class="muted">期望错题：${(item.expected_wrong_questions || []).join("、") || "无"} · 预测错题：${(item.predicted_wrong_questions || []).join("、") || "无"}</p>
          </div>
          <span class="score-pill ${item.passed ? "ok" : "bad"}">${escapeHtml(item.actual_score)} / ${escapeHtml(item.expected_score)}</span>
        </div>
      `).join("")}
    </div>
    <p class="muted">${escapeHtml(evaluation.rubric || "")}</p>
  `;
}

async function renderManagementPage() {
  await refreshManagementData();
  renderManagement();
}

async function refreshManagementData() {
  const [assignments, classes, submissions, evaluation] = await Promise.all([
    api("/api/assignments"),
    api("/api/classes"),
    api("/api/submissions"),
    api("/api/evaluation/grading"),
  ]);
  state.assignments = assignments.data;
  state.classes = classes.data;
  state.submissions = submissions.data;
  state.evaluation = evaluation.data;
}

async function handleCreateQuestion(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/question-bank", {
      method: "POST",
      body: JSON.stringify({
        title: form.get("title"),
        subject: form.get("subject"),
        question_type: form.get("question_type"),
        question: form.get("question"),
        standard_answer: form.get("standard_answer"),
        full_score: Number(form.get("full_score")),
        knowledge_points: String(form.get("knowledge_points") || "").split(",").map((item) => item.trim()).filter(Boolean),
      }),
    });
    await refreshManagementData();
    showToast("题目已加入题库");
    renderManagement();
  } catch (error) {
    showToast(error.message);
  }
}

async function handleCreateClass(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await api("/api/classes", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        grade: form.get("grade"),
        teacher_name: form.get("teacher_name"),
      }),
    });
    await refreshManagementData();
    showToast("班级已创建");
    renderManagement();
  } catch (error) {
    showToast(error.message);
  }
}

async function handleBulkUpload(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const assignmentId = Number(form.get("assignment_id"));
  try {
    const response = await api("/api/bulk-upload", {
      method: "POST",
      body: JSON.stringify({
        auto_ocr: true,
        auto_grade: true,
        items: state.students.map((student) => ({
          student_id: student.id,
          assignment_id: assignmentId,
          image_name: `bulk-${student.name}.png`,
          image_data: "",
        })),
      }),
    });
    await refreshManagementData();
    showToast(`已创建 ${response.data.count} 条提交`);
    renderManagement();
  } catch (error) {
    showToast(error.message);
  }
}

async function handleAnnotation(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const submissionId = form.get("submission_id");
  try {
    await api(`/api/submissions/${submissionId}/annotations`, {
      method: "POST",
      body: JSON.stringify({
        teacher_id: Number(form.get("teacher_id")) || null,
        label: form.get("label"),
        comment: form.get("comment"),
        corrected_score: Number(form.get("corrected_score")),
      }),
    });
    await refreshManagementData();
    showToast("标注已保存");
    renderManagement();
  } catch (error) {
    showToast(error.message);
  }
}

function findAssignment(subject, type) {
  return (
    state.assignments.find((item) => item.subject === subject && item.question_type === type) ||
    state.assignments.find((item) => item.subject === subject)
  );
}

function getTypes(subject) {
  return unique(state.assignments.filter((item) => item.subject === subject).map((item) => item.question_type));
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function statusClassName(status = "") {
  if (status.includes("复核")) return "review";
  if (status.includes("AI") || status.includes("返回")) return "done";
  return "wait";
}

function percent(value) {
  const number = Number(value) || 0;
  return `${Math.round(number * 100)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  const old = document.querySelector(".toast");
  if (old) old.remove();
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 2600);
}
