const app = document.querySelector("#app");
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

// ========== State ==========
const state = {
  students: [],
  assignments: [],
  classes: [],
  submissions: [],
  evaluation: null,
  runtime: null,
  teacherFilter: "全部",
  uploadStep: 1,
  selectedFile: null,
  selectedPreview: "",
  selectedFiles: [],
  selectedPreviews: [],
  lastSubmissionId: null,
  quickDemoRunning: false,
  ocrTestFile: null,
  ocrTestPreview: "",
  ocrTest: null,
  questionReviewResults: {},
};

document.addEventListener("DOMContentLoaded", init);
window.addEventListener("hashchange", renderRoute);

async function init() {
  try {
    showAppLoading("正在连接后端服务", "正在加载学生、作业、班级和运行模式配置。");
    await loadBaseData();
    if (!location.hash) location.hash = "#home";
    renderRoute();
  } catch (error) {
    renderFatalError(error);
  }
}

async function loadBaseData() {
  const [students, assignments, classes, runtime] = await Promise.all([
    api("/api/students"),
    api("/api/assignments"),
    api("/api/classes"),
    api("/api/runtime/status"),
  ]);
  state.students = students.data;
  state.assignments = assignments.data;
  state.classes = classes.data;
  state.runtime = runtime.data;
}

// ========== API ==========
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (error) {
    throw new Error("网络失败或后端未启动，请确认 FastAPI 服务正在 http://127.0.0.1:8000 运行。");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(friendlyErrorMessage(detail.detail || response.statusText || "请求失败", response.status));
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

// ========== Router ==========
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

// ========== Home ==========
// 首页首屏：用于比赛开场快速传达产品定位和核心演示结果。
function renderHome() {
  app.innerHTML = `
    ${modeBanner()}
    <section class="hero product-hero">
      <div class="hero-copy">
        <span class="feature-tag">多学科 AI 智能作业批改系统</span>
        <h1>希沃智评</h1>
        <p>面向学生和教师的作业批改 Demo，覆盖图片上传、OCR 识别、数学过程分、主观题评价、知识点薄弱分析和班级学情报告。</p>
        <div class="hero-actions">
          <a class="btn xl" href="#student">进入 Demo</a>
          <button id="quickDemoHome" class="btn secondary xl" type="button" data-quick-demo data-quick-demo-label="快速演示：使用固定 5 题数学卷">快速演示：使用固定 5 题数学卷</button>
          <a class="btn secondary xl" href="#teacher">教师工作台</a>
        </div>
        <div id="quickDemoStatus" class="quick-demo-status" aria-live="polite"></div>
        <div class="hero-proof">
          <span>固定 5 题数学卷</span>
          <span>43 / 50 稳定输出</span>
          <span>第 3、4 题可解释扣分</span>
        </div>
      </div>
      <div class="hero-preview" aria-label="AI 批改结果预览">
        ${heroPreviewCard()}
      </div>
    </section>
    <section class="flow-section">
      <div class="flow-card">
        ${flowStep("01", "上传试卷", "学生上传完整答题卡图片，保留题干与作答过程。")}
        ${flowStep("02", "AI 逐题批改", "OCR 结构化识别后，按题目拆分给分并定位错误步骤。")}
        ${flowStep("03", "生成学情报告", "教师端汇总正确率、薄弱点和后续教学建议。")}
      </div>
    </section>
    <section class="capability-section">
      <div class="section-head">
        <div>
          <h2>核心能力</h2>
          <p>比赛 Demo 重点突出智能批改、个性化评语和学情分析。</p>
        </div>
      </div>
      <div class="feature-grid">
        ${featureCard("OCR 识别", "结构化提取题干、步骤和学生作答。")}
        ${featureCard("数学过程分", "按思路、计算、答案拆分给分。")}
        ${featureCard("个性化评语", "根据表现生成温和具体的反馈。")}
        ${featureCard("薄弱点分析", "自动归因知识点和错因。")}
        ${featureCard("教师复核", "支持改分、评语和复核备注。")}
        ${featureCard("班级报告", "汇总正确率、薄弱点和教学建议。")}
      </div>
    </section>
  `;
  document.querySelector("#quickDemoHome")?.addEventListener("click", () => runQuickDemo("home"));
}

function featureCard(title, text) {
  return `<article class="feature-card"><span class="card-mark"></span><h3>${title}</h3><p>${text}</p></article>`;
}

function heroPreviewCard() {
  return `
    <div class="ai-preview-card">
      <div class="preview-head">
        <div>
          <span class="feature-tag">AI 批改结果预览</span>
          <h3>数学练习卷批改预览</h3>
        </div>
        <span class="status done">AI 已批改</span>
      </div>
      <div class="preview-score">
        <strong>43</strong><span>/ 50</span>
      </div>
      <div class="preview-stats">
        <div><span>正确题</span><strong>3</strong></div>
        <div><span>部分正确</span><strong>1</strong></div>
        <div><span>需订正</span><strong>1</strong></div>
      </div>
      <div class="preview-question is-wrong">
        <span>第 3 题 · 计算题</span>
        <strong>6 / 10 · 计算错误</strong>
        <p>退位减法错误，正确结果为 62。</p>
      </div>
      <div class="preview-question is-partial">
        <span>第 4 题 · 解方程</span>
        <strong>7 / 10 · 部分正确</strong>
        <p>前两步正确，最后除以 3 错误，应为 x = 5。</p>
      </div>
      <div class="tag-list">
        <span class="tag">薄弱点：减法计算</span>
        <span class="tag">一元一次方程</span>
        <a class="btn ghost small" href="#student">查看逐题分析</a>
      </div>
    </div>
  `;
}

function flowStep(no, title, text) {
  return `
    <article class="flow-step">
      <span>${no}</span>
      <div>
        <strong>${title}</strong>
        <p>${text}</p>
      </div>
    </article>
  `;
}

function modeBanner() {
  const runtime = state.runtime || {};
  const stable = Boolean(runtime.demo_fixed_math_paper_ocr);
  const safety = runtimeSafety(runtime);
  const title = stable ? "当前模式：比赛稳定演示模式" : "当前模式：真实识别模式";
  const description = stable
    ? "上传数学练习卷后，系统将使用固定 5 题结构化 OCR，保证比赛现场演示稳定。"
    : "系统将调用 LLM 视觉 OCR / PaddleOCR / 云 OCR 识别真实图片，适合第二阶段泛化验证。";
  return `
    <section class="mode-banner ${stable ? "stable" : "real"}">
      <div>
        <strong>${title}</strong>
        <p>${description}</p>
      </div>
      <div class="tag-list">
        <span class="tag">${stable ? "稳定 Demo OCR" : "真实识别链路"}</span>
        <span class="tag ${safety.safe ? "success" : "danger"}">当前可安全演示：${escapeHtml(safety.label)}</span>
        <span class="tag">逐题批改</span>
        <span class="tag">过程分</span>
        <span class="tag">教师复核</span>
        <span class="tag">班级报告</span>
      </div>
      <div class="mode-tech-tags">
        <span>OCR：${escapeHtml(runtime.ocr_provider ?? "-")}</span>
        <span>固定演示：${stable ? "开启" : "关闭"}</span>
        <span>LLM：${runtime.llm_enabled ? "已配置" : "未启用"}</span>
        <span>${escapeHtml(safety.message)}</span>
      </div>
    </section>
  `;
}

function runtimeSafety(runtime = {}) {
  const provider = String(runtime.ocr_provider || "").toLowerCase();
  const knownProviders = ["mock", "llm", "paddle", "baidu", "tencent"];
  if (runtime.demo_fixed_math_paper_ocr) {
    return { safe: true, label: "是", message: "稳定演示模式已开启，现场演示不会依赖真实 OCR 网络链路。" };
  }
  if (!knownProviders.includes(provider)) {
    return { safe: false, label: "否", message: "OCR_PROVIDER 配置错误，请检查 .env。" };
  }
  if (provider === "mock") {
    return { safe: false, label: "否", message: "当前关闭了固定演示但 OCR_PROVIDER=mock，建议切回演示模式或配置真实 OCR。" };
  }
  if (provider === "llm") {
    if (!runtime.llm_enabled || !runtime.llm_vision_enabled) {
      return { safe: false, label: "否", message: "真实 OCR 模式未启用 LLM 视觉识别，请检查 LLM_ENABLED / LLM_VISION_OCR。" };
    }
    if (!runtime.llm_has_key) {
      return { safe: false, label: "否", message: "真实 OCR 配置不完整，请填写 KIMI_API_KEY 或切换演示模式。" };
    }
    return { safe: true, label: "真实 OCR 模式可用", message: "真实 OCR 模式配置完整，仍建议比赛现场优先使用稳定演示模式。" };
  }
  return { safe: true, label: "真实 OCR 模式可用", message: `${provider || "OCR"} 识别链路已选择，请确认本地/云端依赖可访问。` };
}

// ========== Student Upload ==========
// 学生上传页：按演示流程串联上传、OCR、批改和结果跳转。
function renderStudent() {
  state.uploadStep = 1;
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
        <div class="button-row">
          <button id="quickDemoStudent" class="btn secondary" type="button" data-quick-demo data-quick-demo-label="快速演示：使用固定 5 题数学卷">快速演示：使用固定 5 题数学卷</button>
          <a class="btn ghost" href="#teacher">查看教师端</a>
        </div>
      </div>
      ${modeBanner()}
      ${uploadSteps()}
      <div class="upload-grid">
        <form id="uploadForm" class="panel form-grid upload-panel">
          <div class="form-two-col">
            <div class="field">
              <label for="studentSelect">学生</label>
              <select id="studentSelect">${state.students.map((student) => `<option value="${student.id}" ${student.id === defaultStudent ? "selected" : ""}>${student.name} · ${student.class_name}</option>`).join("")}</select>
            </div>
            <div class="field">
              <label for="subjectSelect">学科 / 模式</label>
              <select id="subjectSelect">${subjects.map((subject) => `<option value="${subject}" ${subject === defaultSubject ? "selected" : ""}>${subject}</option>`).join("")}</select>
            </div>
          </div>
          <div class="field">
            <label for="typeSelect">题型</label>
            <select id="typeSelect">${types.map((type) => `<option value="${type}">${type}</option>`).join("")}</select>
          </div>
          <div id="essayPromptWrap">${compositionPromptMarkup(defaultSubject, types[0])}</div>
          <div id="assignmentInfo" class="card assignment-card">${assignmentInfo(defaultSubject, types[0])}</div>
          <div class="field upload-field">
            <label for="imageInput">上传试卷图片（支持多张）</label>
            <p class="muted">支持上传多张图片，请按试卷顺序上传。例如：先上传题目页，再上传答题页；也可以上传单张完整答题卡。</p>
            <div id="uploadDrop" class="upload-drop ${state.selectedFiles.length ? "has-files" : ""}">
              <input id="imageInput" type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" multiple />
              <div id="previewWrap">${uploadPreviewMarkup()}</div>
            </div>
          </div>
          <div class="button-row">
            <button id="gradeBtn" class="btn xl" type="submit">开始 AI 批改</button>
            <span id="uploadStatus" class="muted"></span>
          </div>
        </form>
        <aside class="panel demo-guide">
          <span class="feature-tag">比赛稳定演示</span>
          <h3>固定 5 题数学练习卷</h3>
          <p class="muted">系统会识别题目和学生答题过程，并逐题给出得分、错因、知识点和评语。</p>
          <div class="demo-paper-list">
            <div><strong>第 1 题：四则混合运算</strong><span>正确，展示运算顺序和完整得分。</span></div>
            <div><strong>第 2 题：一元一次方程</strong><span>正确，移项和求解步骤完整。</span></div>
            <div><strong>第 3 题：计算错误</strong><span>90 - 28 = 72，定位减法计算问题。</span></div>
            <div><strong>第 4 题：过程正确但最终答案错误</strong><span>前两步正确，最后 x = 4 给部分分。</span></div>
            <div><strong>第 5 题：应用题</strong><span>正确，数量关系和答句完整。</span></div>
          </div>
          <div class="tag-list">
            <span class="tag">43 / 50</span>
            <span class="tag">2 道需订正</span>
            <span class="tag">知识点归因</span>
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
    document.querySelector("#essayPromptWrap").innerHTML = compositionPromptMarkup(subjectSelect.value, typeSelect.value);
  });
  typeSelect.addEventListener("change", () => {
    document.querySelector("#assignmentInfo").innerHTML = assignmentInfo(subjectSelect.value, typeSelect.value);
    document.querySelector("#essayPromptWrap").innerHTML = compositionPromptMarkup(subjectSelect.value, typeSelect.value);
  });
  imageInput.addEventListener("change", handlePreview);
  document.querySelector("#uploadDrop").addEventListener("dragover", handleUploadDrag);
  document.querySelector("#uploadDrop").addEventListener("dragleave", handleUploadDrag);
  document.querySelector("#uploadDrop").addEventListener("drop", handleUploadDrop);
  document.querySelector("#uploadDrop").addEventListener("click", handleUploadListAction);
  uploadForm.addEventListener("submit", handleGradeSubmit);
  document.querySelector("#quickDemoStudent")?.addEventListener("click", () => runQuickDemo("student"));
}

function uploadSteps() {
  return `
    <div class="steps-bar">
      ${["选择学生与题型", "上传试卷", "OCR 识别", "AI 批改", "查看结果"].map((item, index) => `
        <div class="step-item ${stepClass(index + 1)}" data-upload-step="${index + 1}">
          <span>${index + 1}</span>
          <strong>${item}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function stepClass(step) {
  if (state.uploadStep > step) return "completed";
  if (state.uploadStep === step) return "active";
  return "";
}

function updateUploadStep(step) {
  state.uploadStep = step;
  document.querySelectorAll("[data-upload-step]").forEach((item) => {
    const current = Number(item.dataset.uploadStep);
    item.classList.toggle("active", current === step);
    item.classList.toggle("completed", current < step);
  });
}

function uploadPreviewMarkup() {
  if (state.selectedFiles.length) {
    return `
      <div class="multi-upload-list">
        ${state.selectedFiles.map((file, index) => `
          <div class="upload-page-card">
            <div class="upload-page-head">
              <strong>第 ${index + 1} 页</strong>
              <span>${escapeHtml(file.name)} · ${formatFileSize(file.size)}</span>
            </div>
            ${state.selectedPreviews[index] ? `<img class="preview page-thumb" src="${state.selectedPreviews[index]}" alt="第 ${index + 1} 页预览" />` : ""}
            <div class="button-row compact-actions">
              <button class="btn ghost small" type="button" data-page-action="up" data-page-index="${index}" ${index === 0 ? "disabled" : ""}>上移</button>
              <button class="btn ghost small" type="button" data-page-action="down" data-page-index="${index}" ${index === state.selectedFiles.length - 1 ? "disabled" : ""}>下移</button>
              <button class="btn ghost small danger-text" type="button" data-page-action="remove" data-page-index="${index}">删除</button>
            </div>
          </div>
        `).join("")}
        <label class="btn secondary small upload-again" for="imageInput">重新选择图片</label>
      </div>
    `;
  }
  return `
    <div class="upload-empty">
      <strong>拖拽或点击上传数学练习卷</strong>
      <span>支持 JPG / PNG / JPEG，可一次选择多张图片并按页码顺序合并批改。</span>
    </div>
  `;
}

function compositionPromptMarkup(subject, type) {
  if (!isCompositionSelection(subject, type)) return "";
  const placeholder = subject === "英语"
    ? "Write a short passage about your weekend. You should write at least 60 words."
    : "请以《难忘的一天》为题写一篇不少于 600 字的作文。";
  return `
    <div class="field essay-prompt-field">
      <label for="essayPrompt">作文题目 / 写作要求</label>
      <textarea id="essayPrompt" name="essay_prompt" placeholder="${escapeHtml(placeholder)}"></textarea>
      <small>建议填写作文题目，以便 AI 判断是否切题；留空时系统会提示切题判断可能不完整。</small>
    </div>
  `;
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
  const files = Array.from(event.target.files || []);
  const validation = validateImageFiles(files);
  if (!validation.ok) {
    clearSelectedFiles();
    refreshUploadPreview();
    showToast(validation.message);
    return;
  }
  if (!files.length) {
    clearSelectedFiles();
    refreshUploadPreview();
    return;
  }
  Promise.all(files.map(readFileAsDataURL)).then((previews) => {
    state.selectedFiles = files;
    state.selectedPreviews = previews;
    state.selectedFile = files[0] || null;
    state.selectedPreview = previews[0] || "";
    refreshUploadPreview();
    updateUploadStep(2);
  });
}

function handleUploadDrag(event) {
  event.preventDefault();
  event.currentTarget.classList.toggle("is-dragging", event.type === "dragover");
}

function handleUploadDrop(event) {
  event.preventDefault();
  event.currentTarget.classList.remove("is-dragging");
  const files = Array.from(event.dataTransfer.files || []);
  if (!files.length) return;
  const input = document.querySelector("#imageInput");
  const transfer = new DataTransfer();
  files.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  handlePreview({ target: input });
}

function handleUploadListAction(event) {
  const button = event.target.closest("[data-page-action]");
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  const index = Number(button.dataset.pageIndex);
  const action = button.dataset.pageAction;
  if (action === "remove") {
    state.selectedFiles.splice(index, 1);
    state.selectedPreviews.splice(index, 1);
  }
  if (action === "up" && index > 0) {
    swapUploadPages(index, index - 1);
  }
  if (action === "down" && index < state.selectedFiles.length - 1) {
    swapUploadPages(index, index + 1);
  }
  state.selectedFile = state.selectedFiles[0] || null;
  state.selectedPreview = state.selectedPreviews[0] || "";
  refreshUploadPreview();
}

function swapUploadPages(left, right) {
  [state.selectedFiles[left], state.selectedFiles[right]] = [state.selectedFiles[right], state.selectedFiles[left]];
  [state.selectedPreviews[left], state.selectedPreviews[right]] = [state.selectedPreviews[right], state.selectedPreviews[left]];
}

function refreshUploadPreview() {
  const drop = document.querySelector("#uploadDrop");
  const wrap = document.querySelector("#previewWrap");
  if (drop) drop.classList.toggle("has-files", state.selectedFiles.length > 0);
  if (wrap) wrap.innerHTML = uploadPreviewMarkup();
}

function clearSelectedFiles() {
  state.selectedFiles = [];
  state.selectedPreviews = [];
  state.selectedFile = null;
  state.selectedPreview = "";
}

async function handleGradeSubmit(event) {
  event.preventDefault();
  const button = document.querySelector("#gradeBtn");
  const status = document.querySelector("#uploadStatus");
  const subject = document.querySelector("#subjectSelect").value;
  const questionType = document.querySelector("#typeSelect").value;
  const assignment = findAssignment(subject, questionType);
  const studentId = Number(document.querySelector("#studentSelect").value);
  const essayPrompt = document.querySelector("#essayPrompt")?.value?.trim() || "";
  if (isCompositionSelection(subject, questionType) && !essayPrompt) {
    showToast("建议填写作文题目，以便 AI 判断是否切题。");
  }
  if (!state.selectedFiles.length) {
    status.textContent = "请先上传作业图片，或点击“快速演示：使用固定 5 题数学卷”。";
    showToast("没有上传图片：请先选择 JPG / PNG / JPEG 图片。");
    return;
  }

  button.disabled = true;
  let keepStatus = false;
  updateUploadStep(2);
  status.textContent = "上传中...";
  try {
    if (state.selectedFiles.length > 1) {
      await submitBatchGradeFlow({ studentId, subject, questionType, assignment, essayPrompt, status });
      return;
    }
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
        essay_prompt: essayPrompt,
      }),
    });
    updateUploadStep(3);
    status.textContent = "OCR 识别中...";
    const submissionId = upload.data.submission_id;
    await api("/api/ocr", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId }),
    });
    updateUploadStep(4);
    status.textContent = "AI 批改中...";
    await api("/api/grade", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId, subject, question_type: questionType, essay_prompt: essayPrompt }),
    });
    state.lastSubmissionId = submissionId;
    updateUploadStep(5);
    showToast("批改完成");
    location.hash = `#result/${submissionId}`;
  } catch (error) {
    status.textContent = formatStageError(error, "批改流程");
    keepStatus = true;
    showToast(status.textContent);
  } finally {
    button.disabled = false;
    if (!keepStatus) status.textContent = "";
  }
}

async function submitBatchGradeFlow({ studentId, subject, questionType, assignment, essayPrompt, status }) {
  const images = await Promise.all(
    state.selectedFiles.map(async (file, index) => ({
      page_index: index + 1,
      image_name: file.name,
      image_data: await readFileAsDataURL(file),
    })),
  );
  const upload = await api("/api/upload/batch", {
    method: "POST",
    body: JSON.stringify({
      student_id: studentId,
      subject,
      question_type: questionType,
      assignment_id: assignment?.id,
      essay_prompt: essayPrompt,
      images,
    }),
  });
  const { submission_id: submissionId, batch_id: batchId, pages } = upload.data;
  updateUploadStep(3);
  status.textContent = "多页 OCR 识别与顺序合并中...";
  const ocr = await api("/api/ocr/batch", {
    method: "POST",
    body: JSON.stringify({
      submission_id: submissionId,
      batch_id: batchId,
      subject,
      question_type: questionType,
      pages,
    }),
  });
  status.textContent = `已合并 ${ocr.data.merge_summary?.question_count ?? 0} 道题，AI 批改中...`;
  updateUploadStep(4);
  await api("/api/grade/batch", {
    method: "POST",
    body: JSON.stringify({
      submission_id: submissionId,
      batch_id: batchId,
      student_id: studentId,
      subject,
      question_type: questionType,
      merged_ocr_text: ocr.data.merged_ocr_text,
      questions: ocr.data.questions || [],
      page_results: ocr.data.page_results || [],
      essay_prompt: essayPrompt,
    }),
  });
  state.lastSubmissionId = submissionId;
  updateUploadStep(5);
  showToast("多图合并批改完成");
  location.hash = `#result/${submissionId}`;
}

async function runQuickDemo(source = "home") {
  if (state.quickDemoRunning) return;
  const student = findDefaultStudent();
  const assignment = findDemoAssignment();
  if (!student || !assignment) {
    showToast("缺少张三学生或自动识别答题卡作业，请先确认示例数据已初始化。");
    return;
  }

  state.quickDemoRunning = true;
  applyDemoSelections(student, assignment);
  try {
    setQuickDemoStage("正在上传演示试卷", 2);
    const upload = await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({
        student_id: student.id,
        subject: assignment.subject || "自动识别",
        question_type: assignment.question_type || "答题卡",
        assignment_id: assignment.id,
        image_name: "demo-fixed-math-paper.png",
        image_data: createDemoPaperImageData(),
      }),
    });

    const submissionId = upload.data.submission_id;
    setQuickDemoStage("正在进行 OCR 识别", 3);
    await api("/api/ocr", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId }),
    });

    setQuickDemoStage("正在进行 AI 逐题批改", 4);
    await api("/api/grade", {
      method: "POST",
      body: JSON.stringify({
        submission_id: submissionId,
        subject: assignment.subject || "自动识别",
        question_type: assignment.question_type || "答题卡",
      }),
    });

    setQuickDemoStage("正在生成结果", 5);
    state.lastSubmissionId = submissionId;
    showToast(source === "home" ? "快速演示已生成，正在进入批改结果" : "演示批改完成");
    location.hash = `#result/${submissionId}`;
  } catch (error) {
    showToast(formatStageError(error, "一键演示"));
    const status = document.querySelector("#quickDemoStatus") || document.querySelector("#uploadStatus");
    if (status) status.textContent = formatStageError(error, "一键演示");
  } finally {
    state.quickDemoRunning = false;
    resetQuickDemoButtons();
  }
}

function setQuickDemoStage(message, step) {
  if (step) updateUploadStep(step);
  document.querySelectorAll("[data-quick-demo]").forEach((button) => {
    button.disabled = true;
    button.textContent = message;
  });
  const status = document.querySelector("#quickDemoStatus") || document.querySelector("#uploadStatus");
  if (status) status.textContent = message;
}

function resetQuickDemoButtons() {
  document.querySelectorAll("[data-quick-demo]").forEach((button) => {
    button.disabled = false;
    button.textContent = button.dataset.quickDemoLabel || "快速演示：使用固定 5 题数学卷";
  });
}

function applyDemoSelections(student, assignment) {
  const studentSelect = document.querySelector("#studentSelect");
  const subjectSelect = document.querySelector("#subjectSelect");
  const typeSelect = document.querySelector("#typeSelect");
  if (studentSelect) studentSelect.value = String(student.id);
  if (subjectSelect && typeSelect) {
    subjectSelect.value = assignment.subject;
    const nextTypes = getTypes(assignment.subject);
    typeSelect.innerHTML = nextTypes.map((type) => `<option value="${type}">${type}</option>`).join("");
    typeSelect.value = assignment.question_type;
    const assignmentInfoNode = document.querySelector("#assignmentInfo");
    if (assignmentInfoNode) assignmentInfoNode.innerHTML = assignmentInfo(assignment.subject, assignment.question_type);
  }
  if (state.selectedPreview || state.selectedFiles.length) {
    clearSelectedFiles();
    const previewWrap = document.querySelector("#previewWrap");
    if (previewWrap) previewWrap.innerHTML = uploadPreviewMarkup();
  }
}

function findDefaultStudent() {
  return (
    state.students.find((student) => student.name === "张三" && student.role !== "teacher") ||
    state.students.find((student) => student.role !== "teacher") ||
    state.students[0]
  );
}

function findDemoAssignment() {
  return (
    state.assignments.find((item) => item.subject === "自动识别" && ["答题卡", "整张答题卡"].includes(item.question_type)) ||
    state.assignments.find((item) => item.question_type === "答题卡") ||
    state.assignments[0]
  );
}

function createDemoPaperImageData() {
  const canvas = document.createElement("canvas");
  canvas.width = 900;
  canvas.height = 1280;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#eaf2ff";
  ctx.fillRect(0, 0, canvas.width, 86);
  ctx.fillStyle = "#111827";
  ctx.font = "700 28px Microsoft YaHei, Arial";
  ctx.textAlign = "center";
  ctx.fillText("数学练习卷", canvas.width / 2, 54);
  ctx.textAlign = "left";
  ctx.font = "20px Microsoft YaHei, Arial";
  ctx.fillText("姓名：张三      班级：七年级一班      日期：2026-05-10", 70, 125);
  const lines = [
    "1. 计算：36 ÷ 4 + 5 × 2",
    "   36 ÷ 4 = 9",
    "   5 × 2 = 10",
    "   9 + 10 = 19",
    "   答：19",
    "",
    "2. 解方程：2x + 3 = 11",
    "   2x = 11 - 3",
    "   2x = 8",
    "   x = 4",
    "   答：x = 4",
    "",
    "3. 计算：15 × 6 - 28",
    "   15 × 6 = 90",
    "   90 - 28 = 72",
    "   答：72",
    "",
    "4. 解方程：3x - 5 = 10",
    "   3x = 10 + 5",
    "   3x = 15",
    "   x = 4",
    "   答：x = 4",
    "",
    "5. 应用题：小明买了 3 支铅笔，每支 2 元，又买了 1 本笔记本 5 元，一共用了多少钱？",
    "   3 × 2 = 6（元）",
    "   6 + 5 = 11（元）",
    "   答：一共用了 11 元。",
  ];
  ctx.font = "22px Microsoft YaHei, Arial";
  ctx.fillStyle = "#0f172a";
  let y = 180;
  lines.forEach((line) => {
    if (line.startsWith("5. 应用题")) {
      wrapCanvasText(ctx, line, 70, y, 760, 32);
      y += 64;
      return;
    }
    ctx.fillText(line, 70, y);
    y += line ? 36 : 20;
  });
  ctx.strokeStyle = "#dbe7fb";
  ctx.lineWidth = 3;
  ctx.strokeRect(36, 36, canvas.width - 72, canvas.height - 72);
  return canvas.toDataURL("image/png");
}

function wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight) {
  let line = "";
  for (const char of text) {
    const testLine = line + char;
    if (ctx.measureText(testLine).width > maxWidth && line) {
      ctx.fillText(line, x, y);
      line = char;
      y += lineHeight;
    } else {
      line = testLine;
    }
  }
  if (line) ctx.fillText(line, x, y);
}

// ========== Result ==========
// 批改结果页：核心展示页，突出总分、逐题过程分和错因定位。
async function renderResult(submissionId) {
  if (!submissionId) {
    app.innerHTML = emptyState("没有可用提交记录", "请先上传作业图片，或点击首页的一键演示按钮生成演示提交。", "#student", "去上传");
    return;
  }
  showAppLoading("加载提交详情中", "正在读取 OCR、AI 批改结果和学生个人报告。");
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
            <button class="btn secondary" type="button" data-export-report="${submission.id}">导出学生报告</button>
            <button class="btn ghost" type="button" data-export-json="${submission.id}">导出 JSON</button>
            <a class="btn secondary" href="#student">继续上传</a>
            <a class="btn ghost" href="#teacher/${submission.id}">教师复核</a>
          </div>
        </div>
        <div class="result-grid result-page-grid">
          <aside class="panel paper-side">
            <div class="panel-title-row">
              <div>
            <h3>原始作业图片</h3>
                <p class="muted">保留原始答题卡，便于教师对照复核。</p>
              </div>
            </div>
            ${paperImageGallery(submission)}
            <h3>OCR 识别结果</h3>
            ${engineInfo(submission)}
            ${ocrPreview(submission)}
            ${batchMergeSummary(submission)}
          </aside>
          <div class="panel grading-side">
            ${gradingDetail(submission)}
          </div>
        </div>
        <div class="panel weak-panel" style="margin-top:18px">
          <h3>个人薄弱点</h3>
          ${weakPointList(report.data.weak_points)}
          <p class="muted">${escapeHtml(report.data.personal_suggestion)}</p>
        </div>
      </section>
    `;
    document.querySelector("#regradeCurrent")?.addEventListener("click", rerunCurrentSubmission);
    bindQuestionNavigation();
    bindExportButtons(submission);
  } catch (error) {
    app.innerHTML = errorState("加载提交详情失败", error, "#student", "返回上传页");
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
    showToast(formatStageError(error, button.textContent.includes("批改") ? "AI 批改" : "OCR 识别"));
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
      <div class="score">${formatScore(score)}<small> / ${formatScore(full)}</small></div>
      <strong>${submission.grading_result?.is_correct ? "答案正确" : "需要订正"}</strong>
    </div>
  `;
}

function ocrPreview(submission) {
  const paper = parseJson(submission.ocr_text);
  const questions = Array.isArray(paper?.questions) ? paper.questions : [];
  const pageResults = Array.isArray(paper?.page_results) ? paper.page_results : [];
  if (pageResults.length) {
    return `
      <div class="ocr-paper">
        <div class="section-head compact">
          <div>
            <strong>多图 OCR 结果</strong>
            <p class="muted">${pageResults.length} 页 · 合并出 ${questions.length} 道题</p>
          </div>
        </div>
        <div class="page-ocr-list">
          ${pageResults.map((page) => `
            <div class="ocr-question">
              <strong>第 ${escapeHtml(page.page_index)} 页 · ${escapeHtml(page.engine || "OCR")}</strong>
              <p>${escapeHtml(summarizeText(page.ocr_text || "", 180))}</p>
            </div>
          `).join("")}
        </div>
        ${questions.length ? `<h3>合并后的题目与答案</h3><div class="ocr-question-list">${questions.map((question) => `
          <div class="ocr-question">
            <strong>第 ${escapeHtml(question.question_no)} 题 · 来源页 ${escapeHtml((question.source_pages || []).join("、") || "-")}</strong>
            <p>${escapeHtml(question.question_text || "")}</p>
            <div class="ocr-steps">${formatStudentAnswer(question.student_answer).split("\n").filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("")}</div>
          </div>
        `).join("")}</div>` : ""}
      </div>
    `;
  }
  if (!questions.length) {
    return `<div class="ocr-box">${escapeHtml(submission.ocr_text || "暂无 OCR 内容")}</div>`;
  }
  return `
    <div class="ocr-paper">
      <div class="section-head compact">
        <div>
          <strong>${escapeHtml(paper.paper_title || "识别试卷")}</strong>
          <p class="muted">${escapeHtml(paper.subject || "自动识别")} · ${questions.length} 道题</p>
        </div>
      </div>
      <div class="ocr-question-list">
        ${questions.map((question) => `
          <div class="ocr-question">
            <strong>第 ${escapeHtml(question.question_no)} 题</strong>
            <p>${escapeHtml(question.question_text || "")}</p>
            <div class="ocr-steps">${formatStudentAnswer(question.student_answer).split("\n").filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("")}</div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function gradingDetail(submission) {
  const result = submission.grading_result || {};
  const isComposition = submission.subject === "英语" || submission.subject === "语文";
  return `
    ${resultSummaryCard(submission)}
    ${compositionResultCard(submission)}
    ${presentationGuide(submission)}
    ${questionQuickNav(result)}
    ${answerSheetDetails(result)}
    <div class="result-analysis-card">
      <h3>${isComposition ? "内容与表达分析" : "整体过程分析"}</h3>
      <p class="muted">${escapeHtml(result.process_analysis || result.content_analysis || "暂无分析")}</p>
      ${result.structure_analysis ? `<p class="muted">${escapeHtml(result.structure_analysis)}</p>` : ""}
      ${result.language_analysis ? `<p class="muted">${escapeHtml(result.language_analysis)}</p>` : ""}
      ${mistakeBlock(result)}
      ${result.correct_solution ? `<h3>正确解法</h3><div class="code-box">${escapeHtml(result.correct_solution)}</div>` : ""}
      ${result.revised_example ? `<h3>修改示例</h3><div class="code-box">${escapeHtml(result.revised_example)}</div>` : ""}
      <div class="result-two-col">
        <div>
          <h3>知识点</h3>
          <div class="tag-list">${(result.knowledge_points || []).map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("") || "<span class='muted'>暂无</span>"}</div>
        </div>
        <div>
          <h3>薄弱点</h3>
          <div class="tag-list">${(result.weak_points || []).map((point) => `<span class="tag danger">${escapeHtml(point)}</span>`).join("") || "<span class='muted'>暂无明显薄弱点</span>"}</div>
        </div>
      </div>
      <h3>个性化评语</h3>
      <p class="muted">${escapeHtml(result.comment || "暂无评语")}</p>
      <h3>学习建议</h3>
      <p class="muted">${escapeHtml(result.suggestion || "暂无建议")}</p>
    </div>
  `;
}

function compositionResultCard(submission) {
  if (!isCompositionSelection(submission.subject, submission.question_type)) return "";
  const result = submission.grading_result || {};
  const topicRelevance = result.ai_metadata?.topic_relevance || result.ai_metadata?.essay_prompt
    ? (result.ai_metadata?.topic_relevance || "AI 已结合作文题目和作文正文进行切题判断。")
    : "未填写作文题目，AI 主要根据作文正文进行评价，切题判断可能不完整。";
  const errors = [...(result.errors || []), ...(result.mistakes || [])];
  return `
    <div class="composition-card">
      <div class="panel-title-row">
        <div>
          <span class="feature-tag">作文批改</span>
          <h3>作文题目 / 写作要求</h3>
        </div>
        <span class="tag">${escapeHtml(submission.subject)} · ${escapeHtml(submission.question_type)}</span>
      </div>
      <div class="code-box">${escapeHtml(submission.essay_prompt || "未填写作文题目，建议后续补充写作要求以提升切题判断准确性。")}</div>
      <h3>OCR 识别出的作文正文</h3>
      <div class="answer-box"><p>${escapeHtml(submission.ocr_text || "暂无作文正文")}</p></div>
      <div class="result-two-col">
        <div><h3>是否切题</h3><p class="muted">${escapeHtml(topicRelevance)}</p></div>
        <div><h3>优点</h3><div class="tag-list">${(result.strengths || []).map((item) => `<span class="tag success">${escapeHtml(item)}</span>`).join("") || "<span class='muted'>暂无</span>"}</div></div>
      </div>
      <div class="result-two-col">
        <div><h3>内容分析</h3><p class="muted">${escapeHtml(result.content_analysis || "暂无内容分析")}</p></div>
        <div><h3>语言分析</h3><p class="muted">${escapeHtml(result.language_analysis || "暂无语言分析")}</p></div>
      </div>
      ${result.structure_analysis ? `<h3>结构分析</h3><p class="muted">${escapeHtml(result.structure_analysis)}</p>` : ""}
      ${errors.length ? `<h3>错误列表</h3><div class="mistake-list">${errors.map((item) => `<div class="mistake-box"><strong>${escapeHtml(item.original || item.step || "问题")}</strong><p>${escapeHtml(item.reason || item.error || "")}</p>${item.suggestion ? `<p>建议：${escapeHtml(item.suggestion)}</p>` : ""}</div>`).join("")}</div>` : ""}
      ${result.revised_example ? `<h3>修改示例</h3><div class="code-box">${escapeHtml(result.revised_example)}</div>` : ""}
    </div>
  `;
}

function presentationGuide(submission) {
  const result = submission.grading_result || {};
  const sheet = result.ai_metadata?.answer_sheet || {};
  const questions = Array.isArray(sheet.questions) ? sheet.questions : [];
  if (!questions.length) return "";
  const score = result.score ?? sheet.score ?? submission.effective_score ?? 0;
  const full = result.full_score ?? sheet.full_score ?? submission.grading_full_score ?? submission.assignment.full_score;
  return `
    <div class="presentation-guide">
      <div class="panel-title-row">
        <div>
          <span class="feature-tag">演示讲解模式</span>
          <h3>推荐讲解顺序</h3>
        </div>
        <span class="score-pill ok">${escapeHtml(formatScore(score))} / ${escapeHtml(formatScore(full))}</span>
      </div>
      <ol class="guide-timeline">
        <li><span>1</span><p>先看总分：<strong>${escapeHtml(formatScore(score))} / ${escapeHtml(formatScore(full))}</strong>，说明系统已完成整张答题卡逐题批改。</p></li>
        <li><span>2</span><p>讲第 3 题：学生写 <strong>90 - 28 = 72</strong>，系统指出正确结果应为 <strong>62</strong>。 <button class="link-button" type="button" data-scroll-question="${safeDomId(3)}">定位第 3 题</button></p></li>
        <li><span>3</span><p>讲第 4 题：前两步正确，但 <strong>3x = 15 推出 x = 4</strong> 错误，系统给过程分 <strong>7 / 10</strong>。 <button class="link-button" type="button" data-scroll-question="${safeDomId(4)}">定位第 4 题</button></p></li>
        <li><span>4</span><p>查看薄弱点：减法计算、方程求解、除法计算。</p></li>
        <li><span>5</span><p>切换到教师工作台展示教师复核，再进入班级分析展示班级薄弱点和教学建议。</p></li>
      </ol>
    </div>
  `;
}

function questionQuickNav(result) {
  const sheet = result.ai_metadata?.answer_sheet;
  const questions = Array.isArray(sheet?.questions) ? sheet.questions : [];
  if (!questions.length) return "";
  return `
    <div class="question-nav-card">
      <div class="question-nav-title">
        <strong>题目快速导航</strong>
        <span>点击题号定位重点题</span>
      </div>
      <div class="question-nav">
        ${questions.map((question, index) => {
          const no = question.question_no || index + 1;
          const status = questionStatus(question);
          const statusClass = questionStatusClass(question);
          const focusClass = Number(no) === 3 || Number(no) === 4 ? "is-focus" : "";
          return `
            <button class="question-nav-item ${statusClass} ${focusClass}" type="button" data-scroll-question="${safeDomId(no)}">
              <strong>第 ${escapeHtml(no)} 题</strong>
              <span>${status}</span>
              <em>${escapeHtml(formatScore(question.score ?? 0))} / ${escapeHtml(formatScore(question.full_score ?? "-"))}</em>
            </button>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function resultSummaryCard(submission) {
  const result = submission.grading_result || {};
  const sheet = result.ai_metadata?.answer_sheet || {};
  const questions = Array.isArray(sheet.questions) ? sheet.questions : [];
  const score = result.score ?? submission.effective_score ?? submission.ai_score ?? 0;
  const full = result.full_score ?? submission.grading_full_score ?? submission.assignment.full_score;
  const correct = questions.filter((question) => question.is_correct).length;
  const partial = questions.filter((question) => !question.is_correct && questionStatus(question) === "部分正确").length;
  const wrong = questions.filter((question) => !question.is_correct && questionStatus(question) !== "部分正确").length;
  return `
    <div class="result-summary-card summary-card score-card">
      <div>
        <span class="feature-tag">AI 批改总览</span>
        <h3>${escapeHtml(submission.assignment.title)}</h3>
      </div>
      <div class="summary-score"><strong>${escapeHtml(formatScore(score))}</strong><span>/ ${escapeHtml(formatScore(full))}</span></div>
      <div class="summary-grid">
        <div><span>正确题</span><strong>${correct || (result.is_correct ? 1 : 0)}</strong></div>
        <div><span>部分正确</span><strong>${partial}</strong></div>
        <div><span>需订正</span><strong>${questions.length ? wrong : (result.is_correct ? 0 : 1)}</strong></div>
        <div><span>题目数</span><strong>${questions.length || 1}</strong></div>
      </div>
      <div class="tag-list">
        <span class="tag">AI 引擎：${escapeHtml(result.ai_engine || "RuleEngine")}</span>
        ${sheet.fallback ? `<span class="tag">OCR 文本兜底</span>` : ""}
        ${questions.length ? `<span class="tag">逐题批改</span>` : ""}
      </div>
      <div class="summary-comment">${escapeHtml(result.comment || "AI 已完成逐题批改，建议重点订正扣分题并复盘薄弱知识点。")}</div>
      <h3>评分维度</h3>
      ${dimensionBars(result.dimension_scores || {}, full)}
    </div>
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
    <div class="question-section-head">
      <div>
        <h3>逐题批改</h3>
        <p class="muted">共 ${questions.length} 题，正确 ${correctCount} 题，需订正 ${questions.length - correctCount} 题。</p>
      </div>
      <span class="score-pill ok">整卷 ${escapeHtml(formatScore(totalScore))} / ${escapeHtml(formatScore(totalFull))}</span>
    </div>
    <div class="question-list">
      ${questions.map((question, index) => {
        const no = question.question_no || index + 1;
        const score = question.score ?? 0;
        const full = question.full_score ?? "-";
        const mistakes = Array.isArray(question.mistakes) ? question.mistakes : [];
        const status = questionStatus(question);
        const statusClass = questionStatusClass(question);
        const domId = safeDomId(no);
        return `
          <div id="question-${domId}" class="card question-card question-card-v2 ${statusClass}">
            <div class="section-head" style="margin-bottom:10px">
              <div>
                <span class="question-kicker">第 ${escapeHtml(no)} 题 · ${escapeHtml(question.question_type || "题型未定")}</span>
                <h3>${escapeHtml(question.question_text || "未识别到完整题干")}</h3>
              </div>
              <span class="score-pill status-chip ${statusClass}">${status} · ${escapeHtml(formatScore(score))} / ${escapeHtml(formatScore(full))}</span>
            </div>
            <div class="answer-block answer-box">
              <strong>学生作答</strong>
              <p>${escapeHtml(question.student_answer || "未识别到作答")}</p>
            </div>
            <div class="analysis-block">
              <strong>过程分析</strong>
              <p>${escapeHtml(question.process_analysis || question.comment || "暂无分析")}</p>
            </div>
            ${mistakes.length ? `<div class="mistake-list">${mistakes.map((item) => `<div class="mistake-box"><strong>${escapeHtml(item.step || "错误定位")}</strong><p>${escapeHtml(item.error || item.reason || item)}</p></div>`).join("")}</div>` : ""}
            ${question.correct_solution ? `<div class="solution-box"><strong>正确解法</strong><p>${escapeHtml(question.correct_solution)}</p></div>` : ""}
            ${question.suggestion ? `<div class="suggestion-box"><strong>建议</strong><p>${escapeHtml(question.suggestion)}</p></div>` : ""}
            <div class="tag-list" style="margin-top:10px">
              ${(question.knowledge_points || []).map((point) => `<span class="tag knowledge-tag">${escapeHtml(point)}</span>`).join("")}
              ${(question.weak_points || []).map((point) => `<span class="tag danger weak-tag">${escapeHtml(point)}</span>`).join("")}
            </div>
          </div>
        `;
      }).join("")}
    </div>
    ${sheet.warnings?.length ? `<h3>整卷识别提示</h3><div class="card">${sheet.warnings.map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}</div>` : ""}
  `;
}

function bindQuestionNavigation() {
  document.querySelectorAll("[data-scroll-question]").forEach((item) => {
    item.addEventListener("click", () => {
      const target = document.querySelector(`#question-${item.dataset.scrollQuestion}`);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.classList.add("is-highlighted");
      window.setTimeout(() => target.classList.remove("is-highlighted"), 1400);
    });
  });
}

function bindExportButtons(submission) {
  document.querySelectorAll(`[data-export-report="${submission.id}"]`).forEach((button) => {
    button.addEventListener("click", () => exportStudentReport(submission));
  });
  document.querySelectorAll(`[data-export-json="${submission.id}"]`).forEach((button) => {
    button.addEventListener("click", () => exportGradingJson(submission));
  });
}

function exportStudentReport(submission) {
  const filename = `${submission.student.name}-${submission.assignment.title}-个人批改报告.md`.replace(/[\\/:*?"<>|]/g, "-");
  downloadText(filename, buildStudentReportMarkdown(submission), "text/markdown;charset=utf-8");
}

function exportGradingJson(submission) {
  const filename = `submission-${submission.id}-grading-result.json`;
  downloadText(filename, JSON.stringify(buildGradingJson(submission), null, 2), "application/json;charset=utf-8");
}

function buildStudentReportMarkdown(submission) {
  const result = submission.grading_result || {};
  const questions = getAnswerSheetQuestions(result);
  const score = result.score ?? submission.effective_score ?? submission.ai_score ?? 0;
  const full = result.full_score ?? submission.grading_full_score ?? submission.assignment.full_score;
  return `# ${submission.student.name} 个人批改报告

- 班级：${submission.student.class_name || "-"}
- 作业：${submission.assignment.title}
- 学科 / 题型：${submission.subject} / ${submission.question_type}
- 作文题目：${submission.essay_prompt || "-"}
- 总分：${formatScore(score)} / ${formatScore(full)}
- 批改引擎：${result.ai_engine || "-"}
- 批改时间：${submission.created_at || "-"}

## 逐题得分

${questions.map((question, index) => {
  const no = question.question_no || index + 1;
  return `### 第 ${no} 题

- 得分：${formatScore(question.score ?? 0)} / ${formatScore(question.full_score ?? "-")}
- 状态：${questionStatus(question)}
- 题干：${question.question_text || "-"}
- 学生作答：${question.student_answer || "-"}
- 错因：${questionMistakeSummary(question)}
- 知识点：${(question.knowledge_points || []).join("、") || "-"}
- 薄弱点：${(question.weak_points || []).join("、") || "-"}
- 建议：${question.suggestion || question.comment || "-"}
`;
}).join("\n")}

## 总结

- 知识点：${(result.knowledge_points || []).join("、") || "-"}
- 薄弱点：${(result.weak_points || []).join("、") || "-"}
- 个性化评语：${result.comment || "-"}
- 学习建议：${result.suggestion || "-"}
`;
}

function buildGradingJson(submission) {
  const result = submission.grading_result || {};
  return {
    submission_id: submission.id,
    student: submission.student,
    assignment: submission.assignment,
    ocr_text: submission.ocr_text,
    essay_prompt: submission.essay_prompt || "",
    pages: submission.pages || [],
    total_score: result.score ?? submission.effective_score ?? submission.ai_score,
    full_score: result.full_score ?? submission.grading_full_score ?? submission.assignment.full_score,
    questions: getAnswerSheetQuestions(result),
    mistakes: result.mistakes || result.errors || [],
    knowledge_points: result.knowledge_points || [],
    weak_points: result.weak_points || [],
    comment: result.comment || "",
    suggestion: result.suggestion || "",
    grading_engine: result.ai_engine || "",
    created_at: submission.created_at,
  };
}

function downloadText(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
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

function paperImageGallery(submission) {
  const pages = Array.isArray(submission.pages) ? submission.pages.filter((page) => page.image_url) : [];
  if (pages.length > 1) {
    return `
      <div class="paper-page-list">
        ${pages.map((page, index) => `
          <div class="paper-page-card">
            <div class="upload-page-head">
              <strong>第 ${escapeHtml(page.page_index || index + 1)} 页</strong>
              <span>${escapeHtml(page.image_name || page.filename || "")}</span>
            </div>
            <img class="preview paper-preview" src="${escapeHtml(page.image_url)}" alt="第 ${escapeHtml(page.page_index || index + 1)} 页图片" />
          </div>
        `).join("")}
      </div>
    `;
  }
  if (submission.image_url) return `<img class="preview paper-preview" src="${escapeHtml(submission.image_url)}" alt="作业图片" />`;
  return `<div class="empty">暂无图片</div>`;
}

function batchMergeSummary(submission) {
  const ocr = parseJson(submission.ocr_text);
  const merge = ocr?.merge_summary || submission.grading_result?.ai_metadata?.batch_merge;
  const questions = Array.isArray(ocr?.questions) ? ocr.questions : [];
  const pages = Array.isArray(submission.pages) ? submission.pages : [];
  if (!merge && pages.length <= 1) return "";
  return `
    <div class="merge-summary-card">
      <h3>合并识别结果</h3>
      <div class="summary-grid small-grid">
        <div><span>识别页数</span><strong>${merge?.page_count ?? pages.length}</strong></div>
        <div><span>题目数量</span><strong>${merge?.question_count ?? questions.length}</strong></div>
        <div><span>合并状态</span><strong>${merge?.merged === false ? "需复核" : "已合并"}</strong></div>
      </div>
      ${questions.length ? `<div class="merge-question-map">${questions.map((question) => `
        <div>
          <strong>第 ${escapeHtml(question.question_no ?? "-")} 题</strong>
          <span>来源页：${escapeHtml((question.source_pages || []).join("、") || "-")} · 置信度 ${escapeHtml(formatScore((Number(question.confidence) || 0) * 100))}%</span>
          ${question.merge_warning ? `<p>${escapeHtml(question.merge_warning)}</p>` : ""}
        </div>
      `).join("")}</div>` : ""}
    </div>
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
            <div class="mistake-box">
              <strong>${escapeHtml(item.step || item.original || "问题")}</strong>
              <p>${escapeHtml(item.error || item.reason || "")}</p>
              ${item.suggestion ? `<p>建议：${escapeHtml(item.suggestion)}</p>` : ""}
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

// 教师工作台：展示 AI 批改和教师复核的闭环。
// ========== Teacher ==========
async function renderTeacher(selectedId) {
  showAppLoading("加载教师工作台中", "正在读取提交列表、AI 批改结果和教师复核数据。");
  let response;
  try {
    response = await api("/api/submissions");
  } catch (error) {
    app.innerHTML = errorState("加载教师工作台失败", error, "#home", "返回首页");
    return;
  }
  state.submissions = response.data;
  const filteredSubmissions = filterTeacherSubmissions(state.submissions);
  const selected =
    (selectedId && filteredSubmissions.some((item) => String(item.id) === String(selectedId)) ? selectedId : null) ||
    filteredSubmissions[0]?.id ||
    state.submissions[0]?.id;
  let detail = null;
  try {
    detail = selected ? (await api(`/api/submissions/${selected}`)).data : null;
  } catch (error) {
    app.innerHTML = errorState("加载提交详情失败", error, "#teacher", "返回教师工作台");
    return;
  }

  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>教师工作台</h2>
          <p>查看 AI 批改结果，进行确认、调整或返回学生；教师修改会沉淀为二次标注数据，用于后续优化评分规则和模型提示词。</p>
        </div>
        <a class="btn secondary" href="#analysis">班级分析</a>
      </div>
      ${teacherSummary(state.submissions)}
      ${teacherFilterTabs()}
      <div class="teacher-layout">
        <div class="table-wrap teacher-table">
          <div class="table-toolbar">
            <div>
              <strong>作业提交列表</strong>
              <p class="muted">按最新提交排序，点击右侧按钮查看复核详情。</p>
            </div>
            <span class="tag">${filteredSubmissions.length} 条记录</span>
          </div>
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
              ${filteredSubmissions.map((submission) => submissionRow(submission, selected)).join("") || `<tr><td colspan="6"><div class="empty compact">当前筛选下暂无提交</div></td></tr>`}
            </tbody>
          </table>
        </div>
        ${detail ? reviewPanel(detail) : emptyState("没有可用提交记录", "当前没有学生提交。可以先点击一键演示或批量上传 Demo 生成记录。", "#student", "去上传")}
      </div>
    </section>
  `;

  document.querySelectorAll("[data-open-submission]").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = `#teacher/${button.dataset.openSubmission}`;
    });
  });
  document.querySelectorAll("[data-teacher-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.teacherFilter = button.dataset.teacherFilter;
      renderTeacher();
    });
  });

  const reviewForm = document.querySelector("#reviewForm");
  if (reviewForm) reviewForm.addEventListener("submit", handleReviewSubmit);
  const returnBtn = document.querySelector("#returnBtn");
  if (returnBtn) returnBtn.addEventListener("click", handleReturnSubmit);
  document.querySelectorAll(".question-review-form").forEach((form) => {
    form.addEventListener("submit", handleQuestionReviewSubmit);
  });
  document.querySelectorAll("[data-question-review-score]").forEach((input) => {
    input.addEventListener("input", updateQuestionReviewDiff);
    updateQuestionReviewDiff({ currentTarget: input });
  });
  if (detail) bindExportButtons(detail);
}

function filterTeacherSubmissions(submissions) {
  if (state.teacherFilter === "全部") return submissions;
  return submissions.filter((item) => item.status === state.teacherFilter);
}

function teacherFilterTabs() {
  const filters = ["全部", "待批改", "AI 已批改", "教师已复核", "已返回学生"];
  return `
    <div class="filter-tabs">
      ${filters.map((filter) => {
        const count = filter === "全部" ? state.submissions.length : state.submissions.filter((item) => item.status === filter).length;
        return `<button class="${state.teacherFilter === filter ? "active" : ""}" type="button" data-teacher-filter="${filter}">${filter}<span>${count}</span></button>`;
      }).join("")}
    </div>
  `;
}

function teacherSummary(submissions) {
  const total = submissions.length;
  const pending = submissions.filter((item) => item.status.includes("待")).length;
  const reviewed = submissions.filter((item) => item.status.includes("复核")).length;
  const returned = submissions.filter((item) => item.status.includes("返回")).length;
  const scored = submissions
    .map((item) => {
      const score = Number(item.effective_score ?? item.ai_score);
      const full = Number(item.grading_full_score ?? item.assignment?.full_score);
      return Number.isFinite(score) && Number.isFinite(full) && full > 0 ? (score / full) * 100 : null;
    })
    .filter((item) => item !== null);
  const average = scored.length ? scored.reduce((sum, item) => sum + item, 0) / scored.length : 0;
  return `
    <div class="teacher-summary mini-grid">
      <div class="metric-card"><span>提交总数</span><strong>${total}</strong></div>
      <div class="metric-card"><span>待处理</span><strong>${pending}</strong></div>
      <div class="metric-card"><span>教师已复核</span><strong>${reviewed}</strong></div>
      <div class="metric-card"><span>已返回学生</span><strong>${returned}</strong><small>平均得分率 ${formatScore(average)}%</small></div>
    </div>
  `;
}

function submissionRow(submission, selectedId) {
  const score = submission.effective_score ?? "-";
  const full = submission.grading_full_score ?? submission.assignment.full_score;
  const isSelected = String(submission.id) === String(selectedId);
  return `
    <tr class="${isSelected ? "selected" : ""}">
      <td><strong>${escapeHtml(submission.student.name)}</strong><span class="table-subtext">${escapeHtml(shortDate(submission.created_at))}</span></td>
      <td>${escapeHtml(submission.subject)}</td>
      <td>${escapeHtml(submission.question_type)}</td>
      <td><span class="status ${statusClassName(submission.status)}">${escapeHtml(submission.status)}</span></td>
      <td>${score === "-" ? "-" : `${score}/${full}`}</td>
      <td><button class="btn ghost small" type="button" data-open-submission="${submission.id}">${isSelected ? "正在查看" : "查看详情"}</button></td>
    </tr>
  `;
}

function reviewPanel(submission) {
  const result = submission.grading_result || {};
  const full = result.full_score ?? submission.grading_full_score ?? submission.assignment.full_score;
  const aiScore = submission.ai_score ?? result.score ?? 0;
  const teacherScore = submission.teacher_score ?? aiScore;
  const scoreDiff = Number(teacherScore) - Number(aiScore);
  const comment = result.comment || teacherCommentFallback(submission);
  const reviewNote =
    result.review_note ||
    "已查看 OCR 识别、逐题评分和错因归因；如调整分数，请在此说明依据，便于后续沉淀为二次标注样本。";
  return `
    <aside class="teacher-detail">
      <div class="panel review-overview">
        <div class="section-head compact">
          <div>
            <h3>${escapeHtml(submission.student.name)} · ${escapeHtml(submission.assignment.title)}</h3>
            <p class="muted">${escapeHtml(submission.subject)} · ${escapeHtml(submission.question_type)} · ${escapeHtml(submission.image_name || "上传图片")}</p>
          </div>
          <span class="status ${statusClassName(submission.status)}">${escapeHtml(submission.status)}</span>
        </div>
        <div class="button-row compact-actions">
          <button class="btn secondary small" type="button" data-export-report="${submission.id}">导出学生报告</button>
          <button class="btn ghost small" type="button" data-export-json="${submission.id}">导出 JSON</button>
        </div>
        <div class="review-score-strip">
          <div><span>AI 分数</span><strong>${escapeHtml(formatScore(aiScore))} / ${escapeHtml(formatScore(full))}</strong></div>
          <div><span>教师分数</span><strong>${escapeHtml(formatScore(teacherScore))} / ${escapeHtml(formatScore(full))}</strong></div>
          <div><span>分数差异</span><strong>${scoreDiff >= 0 ? "+" : ""}${escapeHtml(formatScore(scoreDiff))}</strong></div>
          <div><span>批改引擎</span><strong>${escapeHtml(result.ai_engine || "RuleEngine")}</strong></div>
        </div>
        ${teacherAiSummary(submission)}
        ${teacherCompositionSummary(submission)}
      </div>
      <div class="panel ai-teacher-diff">
        <span class="feature-tag">AI 与教师差异</span>
        <div class="diff-grid">
          <div><span>AI 原始分数</span><strong>${escapeHtml(formatScore(aiScore))} / ${escapeHtml(formatScore(full))}</strong></div>
          <div><span>教师复核分数</span><strong>${escapeHtml(formatScore(teacherScore))} / ${escapeHtml(formatScore(full))}</strong></div>
          <div><span>调整</span><strong>${scoreDiff >= 0 ? "+" : ""}${escapeHtml(formatScore(scoreDiff))} 分</strong></div>
          <div><span>状态</span><strong>${escapeHtml(submission.status)}</strong></div>
        </div>
        <p class="muted">教师复核结果会作为标注样本沉淀，后续可用于优化同类题目的批改策略。</p>
      </div>
      ${perQuestionReviewPanel(submission)}
      <form id="reviewForm" class="panel review-form form-grid" data-submission-id="${submission.id}">
        <div class="review-form-head">
          <div>
            <h3>教师复核</h3>
            <p class="muted">确认 AI 批改，或根据课堂判断调整分数与评语。</p>
          </div>
          <span class="tag">二次标注闭环</span>
        </div>
        <div class="review-tip">
          <strong>二次标注闭环</strong>
          <p>优先核对扣分题、最终答案和错因归因。保存后状态会变为“教师已复核”。</p>
        </div>
        <div class="field">
          <label for="teacherScore">教师分数</label>
          <input id="teacherScore" name="teacher_score" type="number" min="0" max="${full}" step="0.5" value="${teacherScore}" />
          <small>AI 建议：${escapeHtml(formatScore(aiScore))} / ${escapeHtml(formatScore(full))}，可按教师判断微调。</small>
        </div>
        <div class="field">
          <label>AI 评语</label>
          <div class="readonly-comment">${escapeHtml(result.comment || "暂无 AI 评语")}</div>
        </div>
        <div class="field">
          <label for="teacherComment">评语</label>
          <textarea id="teacherComment" name="comment">${escapeHtml(comment)}</textarea>
        </div>
        <div class="field">
          <label for="reviewNote">复核备注</label>
          <textarea id="reviewNote" name="review_note">${escapeHtml(reviewNote)}</textarea>
        </div>
        <div class="button-row">
          <button class="btn" type="submit">确认复核</button>
          <button id="returnBtn" class="btn warn" type="button" data-submission-id="${submission.id}">返回学生</button>
        </div>
      </form>
    </aside>
  `;
}

function teacherAiSummary(submission) {
  const result = submission.grading_result || {};
  const questions = result.ai_metadata?.answer_sheet?.questions || [];
  const reviewQuestions = questions.filter((question) => !question.is_correct).slice(0, 3);
  const weakPoints = unique([...(result.weak_points || []), ...(result.common_weak_points || [])]).slice(0, 5);
  const summary = result.process_analysis || result.content_analysis || result.comment || "AI 已完成批改，建议教师重点核对扣分题和评语是否符合课堂要求。";
  return `
    <div class="review-ai-card">
      <strong>AI 结论摘要</strong>
      <p>${escapeHtml(summary)}</p>
      ${weakPoints.length ? `<div class="tag-list">${weakPoints.map((point) => `<span class="tag">${escapeHtml(point)}</span>`).join("")}</div>` : ""}
      ${
        reviewQuestions.length
          ? `<div class="teacher-ai-list">${reviewQuestions
              .map(
                (question) => `
                  <div>
                    <span>第 ${escapeHtml(question.question_no || "-")} 题</span>
                    <strong>${escapeHtml(formatScore(question.score))} / ${escapeHtml(formatScore(question.full_score))} · ${escapeHtml(questionStatus(question))}</strong>
                    <p>${escapeHtml(question.process_analysis || question.comment || "建议复核该题扣分依据。")}</p>
                  </div>
                `,
              )
              .join("")}</div>`
          : `<p class="muted">暂无明显错题，教师可快速确认后返回学生。</p>`
      }
    </div>
  `;
}

function teacherCompositionSummary(submission) {
  if (!isCompositionSelection(submission.subject, submission.question_type)) return "";
  const result = submission.grading_result || {};
  return `
    <div class="teacher-composition-card">
      <strong>作文复核信息</strong>
      <div class="compact-card">
        <span class="muted">作文题目 / 写作要求</span>
        <p>${escapeHtml(submission.essay_prompt || "未填写作文题目，建议教师复核切题判断。")}</p>
      </div>
      <div class="compact-card">
        <span class="muted">学生作文正文</span>
        <p>${escapeHtml(summarizeText(submission.ocr_text || "暂无正文", 220))}</p>
      </div>
      <div class="compact-card">
        <span class="muted">AI 作文评分与评语</span>
        <p>${escapeHtml(formatScore(submission.ai_score ?? result.score ?? 0))} 分 · ${escapeHtml(result.comment || "暂无 AI 评语")}</p>
      </div>
    </div>
  `;
}

function perQuestionReviewPanel(submission) {
  const questions = getAnswerSheetQuestions(submission.grading_result || {});
  const teacher = state.students.find((item) => item.role === "teacher");
  if (!questions.length) {
    return `
      <div class="panel question-review-panel">
        <h3>逐题复核</h3>
        <p class="muted">当前提交暂无结构化逐题结果，可先使用整份作业复核。</p>
      </div>
    `;
  }
  return `
    <div class="panel question-review-panel">
      <div class="panel-title-row">
        <div>
          <span class="feature-tag">逐题复核</span>
          <h3>AI + 教师协同批改</h3>
          <p class="muted">逐题核对 AI 分数、错因和知识点；保存后可沉淀为教师标注样本。</p>
        </div>
        <span class="tag">${questions.length} 题</span>
      </div>
      <div class="question-review-list">
        ${questions.map((question, index) => questionReviewCard(submission, question, index, teacher)).join("")}
      </div>
    </div>
  `;
}

function questionReviewCard(submission, question, index, teacher) {
  const no = question.question_no || index + 1;
  const aiScore = Number(question.score ?? 0);
  const full = Number(question.full_score ?? 0);
  const status = questionStatus(question);
  const statusClass = questionStatusClass(question);
  const mistakes = questionMistakeSummary(question);
  const knowledge = (question.knowledge_points || []).join("、") || "暂无";
  const key = questionReviewKey(submission.id, no);
  const saved = state.questionReviewResults[key];
  const teacherScore = saved?.teacherScore ?? aiScore;
  return `
    <form class="question-review-card question-review-form ${statusClass}" data-submission-id="${submission.id}" data-question-no="${escapeHtml(no)}" data-ai-score="${escapeHtml(aiScore)}">
      <div class="question-review-head">
        <div>
          <span class="question-kicker">第 ${escapeHtml(no)} 题 · ${escapeHtml(question.question_type || "题型未定")}</span>
          <h4>${escapeHtml(summarizeText(question.question_text || "未识别题干", 54))}</h4>
        </div>
        <span class="score-pill ${statusClass}">${escapeHtml(status)} · ${escapeHtml(formatScore(aiScore))} / ${escapeHtml(formatScore(full || "-"))}</span>
      </div>
      <div class="review-question-body">
        <div class="answer-box compact-card">
          <strong>学生作答</strong>
          <p>${escapeHtml(summarizeText(question.student_answer || "未识别作答", 140))}</p>
        </div>
        <div class="compact-card">
          <strong>AI 错因</strong>
          <p class="muted">${escapeHtml(mistakes)}</p>
        </div>
        <div class="compact-card">
          <strong>AI 知识点</strong>
          <p class="muted">${escapeHtml(knowledge)}</p>
        </div>
      </div>
      <div class="question-review-fields">
        <div class="field">
          <label>教师分数</label>
          <input name="teacher_question_score" type="number" min="0" max="${escapeHtml(full || 100)}" step="0.5" value="${escapeHtml(teacherScore)}" data-question-review-score />
        </div>
        <div class="field">
          <label>教师评语</label>
          <input name="teacher_question_comment" value="${escapeHtml(saved?.comment || defaultQuestionReviewComment(question))}" />
        </div>
        <div class="field">
          <label>复核原因</label>
          <textarea name="teacher_question_reason">${escapeHtml(saved?.reason || defaultQuestionReviewReason(question))}</textarea>
        </div>
      </div>
      <div class="question-review-footer">
        <label class="check-line"><input name="add_annotation" type="checkbox" ${saved?.addAnnotation === false ? "" : "checked"} /> 加入标注样本</label>
        <span class="score-diff" data-question-review-diff>AI ${escapeHtml(formatScore(aiScore))} vs 教师 ${escapeHtml(formatScore(teacherScore))}</span>
        ${saved ? `<span class="status review">已保存 ${saved.diff >= 0 ? "+" : ""}${escapeHtml(formatScore(saved.diff))} 分</span>` : ""}
        <input type="hidden" name="teacher_id" value="${teacher?.id || ""}" />
        <button class="btn small" type="submit">保存本题复核</button>
      </div>
    </form>
  `;
}

function teacherCommentFallback(submission) {
  const score = Number(submission.effective_score ?? submission.ai_score ?? 0);
  const full = Number(submission.grading_result?.full_score ?? submission.grading_full_score ?? submission.assignment.full_score);
  const rate = full > 0 ? score / full : 0;
  if (rate >= 0.9) return "本次作业完成质量较高，步骤较清晰，建议继续保持规范书写和做后检查。";
  if (rate >= 0.6) return "本次作业已经体现出一定思路，但仍有关键步骤或基础计算需要订正，建议重点复盘错题。";
  return "本次作业暴露出基础知识和答题步骤上的薄弱点，建议先订正错题，再进行同类题巩固。";
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

function updateQuestionReviewDiff(event) {
  const input = event.currentTarget;
  const form = input.closest(".question-review-form");
  if (!form) return;
  const aiScore = Number(form.dataset.aiScore || 0);
  const teacherScore = Number(input.value || 0);
  const diff = teacherScore - aiScore;
  const node = form.querySelector("[data-question-review-diff]");
  if (node) node.textContent = `AI ${formatScore(aiScore)} vs 教师 ${formatScore(teacherScore)}，差异 ${diff >= 0 ? "+" : ""}${formatScore(diff)} 分`;
}

async function handleQuestionReviewSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submissionId = form.dataset.submissionId;
  const questionNo = form.dataset.questionNo;
  const aiScore = Number(form.dataset.aiScore || 0);
  const teacherScore = Number(form.elements.teacher_question_score.value || 0);
  const comment = form.elements.teacher_question_comment.value;
  const reason = form.elements.teacher_question_reason.value;
  const addAnnotation = form.elements.add_annotation.checked;
  const diff = teacherScore - aiScore;
  state.questionReviewResults[questionReviewKey(submissionId, questionNo)] = {
    aiScore,
    teacherScore,
    diff,
    comment,
    reason,
    addAnnotation,
  };

  try {
    if (addAnnotation) {
      await api(`/api/submissions/${submissionId}/annotations`, {
        method: "POST",
        body: JSON.stringify({
          teacher_id: Number(form.elements.teacher_id.value) || null,
          label: `逐题复核-第${questionNo}题`,
          comment: [
            `题号：${questionNo}`,
            `AI 分数：${formatScore(aiScore)}`,
            `教师分数：${formatScore(teacherScore)}`,
            `分数差异：${diff >= 0 ? "+" : ""}${formatScore(diff)}`,
            `教师评语：${comment}`,
            `复核原因：${reason}`,
          ].join("\n"),
          corrected_score: null,
        }),
      });
      showToast(`第 ${questionNo} 题复核已保存并加入标注样本`);
    } else {
      showToast(`第 ${questionNo} 题复核已记录，本次未加入标注样本`);
    }
    await renderTeacher(submissionId);
  } catch (error) {
    showToast(error.message);
  }
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

// 班级分析页：把单份批改结果汇总为教学仪表盘。
// ========== Analysis ==========
async function renderAnalysis() {
  showAppLoading("加载班级分析中", "正在汇总平均分、正确率、薄弱点排行和教学建议。");
  let response;
  try {
    response = await api(`/api/classes/${encodeURIComponent("七年级一班")}/analysis`);
  } catch (error) {
    app.innerHTML = errorState("加载班级分析失败", error, "#home", "返回首页");
    return;
  }
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
      <div class="analysis-grid dashboard-grid" style="margin-top:18px">
        <div class="panel" data-chart-panel="weak">
          <h3>薄弱知识点排行</h3>
          ${rankBars(data.common_weak_points, "knowledge_point", "count")}
        </div>
        <div class="panel" data-chart-panel="accuracy">
          <h3>各题正确率</h3>
          ${accuracyBars(data.question_accuracy)}
        </div>
      </div>
      <div class="analysis-bottom">
        <div class="panel">
          <h3>高频错误</h3>
          ${mistakeRank(data.frequent_mistakes)}
        </div>
        <div class="panel suggestion-panel">
          <span class="feature-tag">AI 教学建议</span>
          <h3>下一课建议安排</h3>
          <p>${escapeHtml(data.teacher_suggestion)}</p>
          <div class="tag-list">
            <span class="tag">针对性讲解</span>
            <span class="tag">错题订正</span>
            <span class="tag">基础计算训练</span>
          </div>
        </div>
      </div>
    </section>
  `;
  document.querySelector("#exportBtn").addEventListener("click", exportClassReport);
  renderECharts(data);
}

function renderECharts(data) {
  if (!window.echarts) return;
  const weakPanel = document.querySelector("[data-chart-panel='weak']");
  const accuracyPanel = document.querySelector("[data-chart-panel='accuracy']");
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

// ========== Management ==========
function renderManagement() {
  const firstAssignment = state.assignments[0];
  const teacher = state.students.find((item) => item.role === "teacher");
  const evaluation = state.evaluation;
  app.innerHTML = `
    <section>
      <div class="section-head">
        <div>
          <h2>管理中心</h2>
          <p>题库管理、班级管理、批量上传、评测中心、真实 OCR 测试和演示数据维护。</p>
        </div>
        <div class="button-row">
          <button id="resetDemoBtn" class="btn warn" type="button">重置演示数据</button>
          <button id="refreshManagement" class="btn ghost" type="button">刷新数据</button>
        </div>
      </div>
      ${demoResetPanel()}
      ${ocrTestPanel()}
      <div class="panel evaluation-panel">
        <h3>评分准确率评测</h3>
        ${evaluation ? evaluationPanel(evaluation) : `<p class="muted">暂无评测数据</p>`}
      </div>
      <div class="management-masonry">
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
        <form id="annotationForm" class="panel form-grid">
          <h3>教师二次标注</h3>
          <p class="muted">将教师复核沉淀为训练样本，后续可用于优化评分规则和模型提示词。</p>
          <div class="field">
            <label>提交记录</label>
            <select name="submission_id">
              ${state.submissions.map((item) => `<option value="${item.id}">${escapeHtml(item.student.name)} · ${escapeHtml(item.assignment.title)}</option>`).join("") || `<option value="" disabled>暂无可标注提交记录</option>`}
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
  document.querySelector("#resetDemoBtn").addEventListener("click", handleDemoReset);
  document.querySelector("#resetDemoPanelBtn").addEventListener("click", handleDemoReset);
  document.querySelector("#questionForm").addEventListener("submit", handleCreateQuestion);
  document.querySelector("#classForm").addEventListener("submit", handleCreateClass);
  document.querySelector("#bulkForm").addEventListener("submit", handleBulkUpload);
  document.querySelector("#annotationForm").addEventListener("submit", handleAnnotation);
  document.querySelector("#ocrTestInput")?.addEventListener("change", handleOcrTestPreview);
  document.querySelector("#ocrTestForm")?.addEventListener("submit", handleOcrTestSubmit);
}

function demoResetPanel() {
  return `
    <div class="panel demo-reset-panel">
      <div>
        <span class="feature-tag">演示维护</span>
        <h3>演示数据重置</h3>
        <p class="muted">仅用于本地比赛演示，会清空当前测试提交、OCR 和批改结果，并恢复默认演示数据；默认学生、班级、作业和题库会保留。</p>
      </div>
      <div class="button-row">
        <button id="resetDemoPanelBtn" class="btn warn" type="button">重置演示数据</button>
        <span class="muted">重置前会弹出确认提示。</span>
      </div>
    </div>
  `;
}

function ocrTestPanel() {
  const runtime = state.runtime || {};
  const stable = Boolean(runtime.demo_fixed_math_paper_ocr);
  const warning = stable
    ? "当前为比赛稳定演示模式。学生端答题卡会优先走固定 Demo OCR；本测试区用于隔离验证真实 OCR，不影响比赛演示流程。"
    : "当前为真实 OCR 模式。若识别失败，请先检查 OCR_PROVIDER、模型配置、图片大小和 API Key。";
  const keyWarning = runtime.ocr_provider === "llm" && !runtime.llm_has_key
    ? `<div class="ocr-test-warning bad">当前 OCR_PROVIDER=llm 但未检测到 API Key，请填写 KIMI_API_KEY 或切回演示模式。</div>`
    : "";
  return `
    <div class="panel ocr-test-panel">
      <div class="panel-title-row">
        <div>
          <span class="feature-tag">真实能力验证</span>
          <h3>真实 OCR 测试</h3>
          <p class="muted">上传一张真实试卷图片，只执行 OCR，不自动批改，避免真实识别波动影响比赛主流程。</p>
        </div>
        <span class="status ${stable ? "wait" : "done"}">${stable ? "演示模式" : "真实模式"}</span>
      </div>
      <div class="runtime-grid">
        ${runtimeItem("OCR_PROVIDER", runtime.ocr_provider ?? "-")}
        ${runtimeItem("DEMO_FIXED_MATH_PAPER_OCR", runtime.demo_fixed_math_paper_ocr ? "true" : "false")}
        ${runtimeItem("LLM_ENABLED", runtime.llm_enabled ? "true" : "false")}
        ${runtimeItem("LLM_VISION_OCR", runtime.llm_vision_enabled ? "true" : "false")}
        ${runtimeItem("LLM_HAS_KEY", runtime.llm_has_key ? "true" : "false")}
        ${runtimeItem("OCR_FALLBACK_TO_MOCK", runtime.ocr_fallback_to_mock ? "true" : "false")}
        ${runtimeItem("ALLOW_MOCK_FOR_UPLOADED_IMAGES", runtime.allow_mock_for_uploaded_images ? "true" : "false")}
      </div>
      <div class="ocr-test-warning">${warning}</div>
      ${keyWarning}
      <div class="ocr-test-grid">
        <form id="ocrTestForm" class="form-grid">
          <div class="field upload-field">
            <label for="ocrTestInput">真实试卷图片</label>
            <div class="upload-drop ocr-test-drop">
              <input id="ocrTestInput" type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" />
              <div id="ocrTestPreview">${ocrTestPreviewMarkup()}</div>
            </div>
          </div>
          <div class="button-row">
            <button id="ocrTestBtn" class="btn" type="submit">只执行 OCR 测试</button>
            <span id="ocrTestStatus" class="muted"></span>
          </div>
        </form>
        <div id="ocrTestResult" class="ocr-test-result">
          ${ocrTestResultMarkup()}
        </div>
      </div>
    </div>
  `;
}

function runtimeItem(label, value) {
  return `<div class="runtime-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function ocrTestPreviewMarkup() {
  if (state.ocrTestPreview) return `<img class="preview" src="${state.ocrTestPreview}" alt="真实 OCR 测试图片" />`;
  return `
    <div class="upload-empty compact">
      <strong>上传真实试卷图片</strong>
      <span>此入口只验证 OCR 识别效果，不会触发 AI 批改和教师端数据闭环。</span>
    </div>
  `;
}

function ocrTestResultMarkup() {
  const result = state.ocrTest;
  if (!result) {
    return `
      <div class="empty compact">
        上传图片后会显示识别状态、题目数量、文本长度、耗时和结构化结果。
      </div>
    `;
  }
  const statusClass = result.status === "成功" ? "done" : result.status.includes("缺失") ? "wait" : "bad";
  return `
    <div class="ocr-test-summary">
      <span class="status ${statusClass}">${escapeHtml(result.status)}</span>
      <div class="mini-grid">
        <div class="metric-card"><span>识别题目数</span><strong>${result.questionCount}</strong></div>
        <div class="metric-card"><span>文本长度</span><strong>${result.textLength}</strong></div>
        <div class="metric-card"><span>耗时</span><strong>${result.duration} ms</strong></div>
        <div class="metric-card"><span>OCR 引擎</span><strong>${escapeHtml(result.engine || "-")}</strong></div>
      </div>
      ${result.message ? `<p class="muted">${escapeHtml(result.message)}</p>` : ""}
      ${result.warnings?.length ? `<div class="card compact-card"><strong>识别提示</strong>${result.warnings.map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}</div>` : ""}
      ${result.questionCount ? structuredOcrSummary(result.structured) : ""}
      <div class="code-box">${escapeHtml(result.rawText || "暂无 OCR 文本")}</div>
    </div>
  `;
}

function structuredOcrSummary(structured) {
  const questions = Array.isArray(structured?.questions) ? structured.questions : [];
  if (!questions.length) return "";
  return `
    <div class="ocr-question-list">
      ${questions.slice(0, 6).map((question) => `
        <div class="ocr-question">
          <strong>第 ${escapeHtml(question.question_no ?? "-")} 题</strong>
          <p>${escapeHtml(question.question_text || "")}</p>
          <div class="ocr-steps">${formatStudentAnswer(question.student_answer).split("\n").filter(Boolean).map((line) => `<span>${escapeHtml(line)}</span>`).join("")}</div>
        </div>
      `).join("")}
    </div>
  `;
}

// 评测中心：用内置样例说明批改结果不是随机给分。
function evaluationPanel(evaluation) {
  const summary = evaluation.summary || {};
  const cases = evaluation.cases || [];
  const averageScoreError = summary.average_score_error ?? average(cases.map((item) => Number(item.score_error) || 0));
  const knowledgeAccuracy = summary.knowledge_point_accuracy ?? rate(cases, (item) => item.knowledge_point_match ?? item.score_pass);
  const processRate = summary.process_score_reasonable_rate ?? rate(cases, (item) => item.process_score_reasonable ?? item.score_pass);
  const teacherConsistency = summary.teacher_review_consistency ?? rate(cases, (item) => item.passed);
  const commentRate = summary.comment_completeness_rate ?? rate(cases, (item) => item.comment_complete ?? true);
  return `
    <p class="muted">评测中心用于验证系统不是随机给分，而是通过内置样例集对 AI 分数、错因识别和知识点识别进行对比评估。</p>
    <div class="evaluation-metric-grid">
      ${evalMetric("测试样例数", summary.total_cases ?? cases.length)}
      ${evalMetric("平均分差", `±${formatScore(averageScoreError)} 分`)}
      ${evalMetric("评分误差合格率", percent(summary.score_within_tolerance_rate))}
      ${evalMetric("错因识别准确率", percent(summary.wrong_question_accuracy))}
      ${evalMetric("知识点识别准确率", percent(knowledgeAccuracy))}
      ${evalMetric("过程分合理率", percent(processRate))}
      ${evalMetric("教师复核一致率", percent(teacherConsistency))}
      ${evalMetric("评语完整率", percent(commentRate))}
    </div>
    <div class="evaluation-table-wrap">
      <table class="evaluation-table">
        <thead>
          <tr>
            <th>题型</th>
            <th>题目摘要</th>
            <th>学生答案摘要</th>
            <th>人工标准分</th>
            <th>AI 批改分</th>
            <th>分数误差</th>
            <th>人工错因</th>
            <th>AI 错因</th>
            <th>错因命中</th>
            <th>知识点命中</th>
          </tr>
        </thead>
        <tbody>
          ${cases.map(evaluationCaseRow).join("")}
        </tbody>
      </table>
    </div>
    <p class="muted">${escapeHtml(evaluation.rubric || "")}</p>
  `;
}

function evalMetric(label, value) {
  return `<div class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function evaluationCaseRow(item) {
  const type = item.question_type || item.subject || "综合";
  const question = item.question_summary || item.name || "内置评测样例";
  const studentAnswer = item.student_answer_summary || item.ocr_summary || "见评测 OCR 文本";
  const expectedMistake = listSummary(item.expected_mistakes || item.expected_wrong_questions, "无明显错因");
  const aiMistake = listSummary(item.ai_mistakes || item.predicted_wrong_questions, "未识别明显错因");
  const wrongHit = Boolean(item.wrong_question_match);
  const knowledgeHit = Boolean(item.knowledge_point_match ?? item.score_pass);
  return `
    <tr>
      <td><strong>${escapeHtml(type)}</strong><span class="table-subtext">${escapeHtml(item.name || "")}</span></td>
      <td>${escapeHtml(summarizeText(question, 64))}</td>
      <td>${escapeHtml(summarizeText(studentAnswer, 72))}</td>
      <td>${escapeHtml(formatScore(item.expected_score))}</td>
      <td>${escapeHtml(formatScore(item.actual_score))}</td>
      <td><span class="score-pill ${item.score_pass ? "ok" : "bad"}">${escapeHtml(formatScore(item.score_error))}</span></td>
      <td>${escapeHtml(summarizeText(expectedMistake, 70))}</td>
      <td>${escapeHtml(summarizeText(aiMistake, 70))}</td>
      <td><span class="status ${wrongHit ? "done" : "wait"}">${wrongHit ? "命中" : "待优化"}</span></td>
      <td><span class="status ${knowledgeHit ? "done" : "wait"}">${knowledgeHit ? "命中" : "待复核"}</span></td>
    </tr>
  `;
}

async function renderManagementPage() {
  showAppLoading("加载管理中心中", "正在读取评测中心、真实 OCR 测试状态、题库和班级数据。");
  try {
    await refreshManagementData();
    renderManagement();
  } catch (error) {
    app.innerHTML = errorState("加载管理中心失败", error, "#home", "返回首页");
  }
}

async function refreshManagementData() {
  const [assignments, classes, submissions, evaluation, runtime] = await Promise.all([
    api("/api/assignments"),
    api("/api/classes"),
    api("/api/submissions"),
    api("/api/evaluation/grading"),
    api("/api/runtime/status"),
  ]);
  state.assignments = assignments.data;
  state.classes = classes.data;
  state.submissions = submissions.data;
  state.evaluation = evaluation.data;
  state.runtime = runtime.data;
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

async function handleDemoReset() {
  const confirmed = window.confirm("确定要重置演示数据吗？这会清空当前测试提交、OCR 和批改结果，并恢复默认演示数据。");
  if (!confirmed) return;
  try {
    const response = await api("/api/demo/reset", { method: "POST" });
    state.selectedFile = null;
    state.selectedPreview = "";
    state.ocrTestFile = null;
    state.ocrTestPreview = "";
    state.ocrTest = null;
    state.questionReviewResults = {};
    await refreshManagementData();
    showToast(response.data?.message || "演示数据已重置");
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
  if (!submissionId) {
    showToast("没有可用提交记录：请先上传作业或运行一键演示。");
    return;
  }
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

function handleOcrTestPreview(event) {
  const file = event.target.files[0];
  const validation = validateImageFile(file);
  if (!validation.ok) {
    state.ocrTestFile = null;
    state.ocrTestPreview = "";
    document.querySelector("#ocrTestPreview").innerHTML = ocrTestPreviewMarkup();
    showToast(validation.message);
    return;
  }
  state.ocrTestFile = file || null;
  if (!file) {
    state.ocrTestPreview = "";
    document.querySelector("#ocrTestPreview").innerHTML = ocrTestPreviewMarkup();
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    state.ocrTestPreview = reader.result;
    document.querySelector("#ocrTestPreview").innerHTML = ocrTestPreviewMarkup();
  };
  reader.readAsDataURL(file);
}

async function handleOcrTestSubmit(event) {
  event.preventDefault();
  const button = document.querySelector("#ocrTestBtn");
  const status = document.querySelector("#ocrTestStatus");
  const file = state.ocrTestFile;
  if (!file) {
    showToast("没有上传图片：请先上传一张真实试卷图片。");
    return;
  }
  const validation = validateImageFile(file);
  if (!validation.ok) {
    showToast(validation.message);
    return;
  }
  const student = findDefaultStudent();
  const assignment = findRealOcrTestAssignment();
  if (!student || !assignment) {
    showToast("缺少可用于 OCR 测试的学生或作业数据");
    return;
  }

  const startedAt = performance.now();
  button.disabled = true;
  status.textContent = "正在上传真实 OCR 测试图片...";
  try {
    const imageData = await readFileAsDataURL(file);
    const upload = await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({
        student_id: student.id,
        subject: assignment.subject || "数学",
        question_type: assignment.question_type || "计算题",
        assignment_id: assignment.id,
        image_name: file.name,
        image_data: imageData,
      }),
    });
    status.textContent = "正在执行 OCR...";
    const submissionId = upload.data.submission_id;
    await api("/api/ocr", {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId }),
    });
    const detail = await api(`/api/submissions/${submissionId}`);
    state.ocrTest = buildOcrTestResult(detail.data, performance.now() - startedAt, null);
    status.textContent = "";
    showToast("真实 OCR 测试完成");
  } catch (error) {
    state.ocrTest = buildOcrTestResult(null, performance.now() - startedAt, error);
    showToast(formatStageError(error, "真实 OCR 测试"));
  } finally {
    button.disabled = false;
    status.textContent = "";
    await refreshManagementData().catch(() => null);
    renderManagement();
  }
}

function findRealOcrTestAssignment() {
  return (
    state.assignments.find((item) => item.subject === "数学" && !["答题卡", "整张答题卡"].includes(item.question_type)) ||
    state.assignments.find((item) => item.subject === "数学") ||
    findDemoAssignment()
  );
}

function buildOcrTestResult(submission, duration, error) {
  const runtime = state.runtime || {};
  if (error) {
    const configMissing = !runtime.ocr_provider || runtime.ocr_provider === "none" || (runtime.ocr_provider === "llm" && !runtime.llm_enabled);
    const keyMissing = runtime.ocr_provider === "llm" && !runtime.llm_has_key;
    return {
      status: configMissing ? "配置缺失" : keyMissing ? "API Key 缺失" : "模型调用失败",
      message: error.message,
      questionCount: 0,
      textLength: 0,
      duration: Math.round(duration),
      engine: runtime.ocr_provider || "-",
      rawText: "",
      structured: null,
      warnings: [],
    };
  }
  const rawText = submission?.ocr_text || "";
  const structured = parseJson(rawText);
  const questions = Array.isArray(structured?.questions) ? structured.questions : [];
  const warnings = submission?.ocr_warnings || [];
  const failed = (submission?.ocr_engine || "").includes("Failed") || Number(submission?.ocr_confidence) === 0;
  const configMissing = !runtime.ocr_provider || runtime.ocr_provider === "none" || (runtime.ocr_provider === "llm" && !runtime.llm_enabled);
  const missingKey = runtime.ocr_provider === "llm" && !runtime.llm_has_key;
  let status = "成功";
  if (configMissing) status = "配置缺失";
  else if (missingKey) status = "API Key 缺失";
  else if (failed) status = "模型调用失败";
  else if (!rawText.trim()) status = "失败";
  return {
    status,
    message: status === "成功" ? "OCR 已完成，可对照下方结构化结果判断真实识别质量。" : "识别未达到可用状态，请检查配置、图片清晰度或模型服务返回。",
    questionCount: questions.length,
    textLength: rawText.length,
    duration: Math.round(duration),
    engine: submission?.ocr_engine || runtime.ocr_provider || "-",
    rawText,
    structured,
    warnings,
  };
}

// ========== Utilities ==========
function findAssignment(subject, type) {
  return (
    state.assignments.find((item) => item.subject === subject && item.question_type === type) ||
    state.assignments.find((item) => item.subject === subject)
  );
}

function getAnswerSheetQuestions(result = {}) {
  const questions = result.ai_metadata?.answer_sheet?.questions;
  return Array.isArray(questions) ? questions : [];
}

function questionReviewKey(submissionId, questionNo) {
  return `${submissionId}-${questionNo}`;
}

function questionMistakeSummary(question) {
  const mistakes = Array.isArray(question.mistakes) ? question.mistakes : [];
  if (!mistakes.length) return question.is_correct ? "未发现明显错误" : (question.process_analysis || question.comment || "建议教师复核该题扣分依据");
  return mistakes
    .map((item) => (typeof item === "string" ? item : (item.error || item.reason || item.step || "")))
    .filter(Boolean)
    .join("；");
}

function defaultQuestionReviewComment(question) {
  if (question.is_correct) return "本题 AI 批改合理，学生步骤和答案基本正确。";
  if (questionStatus(question) === "部分正确") return "本题可保留过程分，但需订正关键错误步骤。";
  return "本题错因明确，建议学生完成同类题巩固。";
}

function defaultQuestionReviewReason(question) {
  if (question.is_correct) return "AI 分数与教师判断一致。";
  return questionMistakeSummary(question);
}

function summarizeText(value, maxLength = 80) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function getTypes(subject) {
  return unique(state.assignments.filter((item) => item.subject === subject).map((item) => item.question_type));
}

function isCompositionSelection(subject, type) {
  const subjectText = String(subject || "");
  const typeText = String(type || "").toLowerCase();
  return ["语文", "英语"].includes(subjectText) && (typeText.includes("作文") || typeText.includes("主观") || typeText.includes("essay"));
}

function formatStudentAnswer(value) {
  if (Array.isArray(value)) return value.map((item) => String(item ?? "")).join("\n");
  return String(value ?? "");
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

function questionStatus(question) {
  if (question.is_correct) return "正确";
  if (question.status === "wrong") return "错误";
  if (question.status === "partial" || (Number(question.score) || 0) > 0) return "部分正确";
  return "错误";
}

function questionStatusClass(question) {
  if (question.is_correct) return "is-correct";
  if (question.status === "wrong") return "is-wrong";
  if (question.status === "partial" || (Number(question.score) || 0) > 0) return "is-partial";
  return "is-wrong";
}

function safeDomId(value) {
  return String(value ?? "").replace(/[^a-zA-Z0-9_-]/g, "-") || "item";
}

function formatScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value ?? "";
  return Math.abs(number - Math.round(number)) < 0.001 ? String(Math.round(number)) : number.toFixed(1);
}

function shortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  return `${month}/${day} ${hour}:${minute}`;
}

function parseJson(value) {
  try {
    return JSON.parse(value || "");
  } catch {
    return null;
  }
}

function percent(value) {
  const number = Number(value) || 0;
  return `${Math.round(number * 100)}%`;
}

function average(values) {
  const usable = values.filter((value) => Number.isFinite(value));
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : 0;
}

function rate(items, predicate) {
  if (!items.length) return 0;
  return items.filter((item) => Boolean(predicate(item))).length / items.length;
}

function listSummary(value, fallback = "-") {
  if (Array.isArray(value)) return value.length ? value.join("、") : fallback;
  return value || fallback;
}

function validateImageFile(file) {
  if (!file) return { ok: true };
  const allowedTypes = ["image/jpeg", "image/png"];
  const lowerName = String(file.name || "").toLowerCase();
  const allowedExt = lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg") || lowerName.endsWith(".png");
  if (!allowedTypes.includes(file.type) && !allowedExt) {
    return { ok: false, message: "图片格式不支持：请上传 JPG、JPEG 或 PNG 图片。" };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return { ok: false, message: `图片过大：当前约 ${formatFileSize(file.size)}，建议压缩到 ${formatFileSize(MAX_UPLOAD_BYTES)} 以内。` };
  }
  return { ok: true };
}

function validateImageFiles(files) {
  if (!files.length) return { ok: true };
  for (const file of files) {
    const validation = validateImageFile(file);
    if (!validation.ok) return validation;
  }
  return { ok: true };
}

function formatFileSize(bytes) {
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(mb >= 10 ? 0 : 1)}MB`;
}

function friendlyErrorMessage(message, status) {
  const text = String(message || "");
  if (status === 401 || text.includes("Invalid Authentication") || text.includes("invalid_authentication")) {
    return "API Key 缺失或无效：请检查 KIMI_API_KEY / LLM_API_KEY，修改 .env 后重启后端。";
  }
  if (status === 413 || text.includes("too large") || text.includes("图片")) {
    return text.includes("图片") ? text : "图片过大：请压缩图片后重试。";
  }
  if (text.includes("NoOCRConfigured") || text.includes("OCR_PROVIDER")) {
    return "OCR_PROVIDER 配置错误或未配置可用 OCR 服务，请检查 .env。";
  }
  if (text.includes("LLM HTTP") || text.includes("模型") || text.includes("timeout") || text.includes("timed out")) {
    return `大模型服务调用失败：${text}`;
  }
  return text || "请求失败，请稍后重试。";
}

function formatStageError(error, stage = "操作") {
  const text = friendlyErrorMessage(error?.message || error, 0);
  if (text.includes("API Key")) return `${stage}失败：${text}`;
  if (text.includes("OCR_PROVIDER")) return `${stage}失败：${text}`;
  if (text.includes("后端未启动")) return `${stage}失败：${text}`;
  return `${stage}失败：${text}`;
}

function showAppLoading(title, text) {
  app.innerHTML = loadingView(title, text);
}

function loadingView(title = "加载中", text = "正在处理，请稍候。") {
  return `
    <div class="state-card loading-card">
      <span class="loading-spinner" aria-hidden="true"></span>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text)}</p>
    </div>
  `;
}

function errorState(title, error, href = "#home", action = "返回首页") {
  return `
    <div class="state-card error-card">
      <span class="state-icon">!</span>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(friendlyErrorMessage(error?.message || error, 0))}</p>
      <div class="button-row">
        <a class="btn" href="${href}">${escapeHtml(action)}</a>
        <button class="btn ghost" type="button" onclick="location.reload()">刷新页面</button>
      </div>
    </div>
  `;
}

function emptyState(title, text, href = "", action = "") {
  return `
    <div class="empty empty-state">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(text)}</p>
      ${href ? `<a class="btn ghost small" href="${href}">${escapeHtml(action || "去处理")}</a>` : ""}
    </div>
  `;
}

function renderFatalError(error) {
  app.innerHTML = errorState("后端连接失败", error, "#home", "重试前请确认服务");
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
