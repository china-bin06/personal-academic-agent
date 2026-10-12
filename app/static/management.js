function renderRequirementTree(parent, nodes) {
  if (!nodes.length) {
    addText(parent, "p", "尚无培养计划节点。");
    return;
  }
  const group = document.createElement("div");
  group.className = "requirement-tree";
  parent.appendChild(group);
  for (const node of nodes) {
    const detail = document.createElement("details");
    detail.open = true;
    addText(detail, "summary", node.name);
    addText(detail, "p", `要求学分：${node.required_credits ?? "未提供"}；获得学分：${node.earned_credits ?? "未提供"}`);
    if (node.credit_shortfall != null) addText(detail, "p", `缺少学分：${node.credit_shortfall}`);
    if (node.relation_raw) addText(detail, "p", `类别关系：${node.relation_raw}`);
    if (node.expected_course_count != null) {
      addText(detail, "p", `共${node.expected_course_count}门；通过${node.passed_course_count ?? "未提供"}门`);
    }
    if (node.courses?.length) {
      const courses = document.createElement("details");
      addText(courses, "summary", `课程明细（${node.courses.length}条）`);
      showTable(courses, "课程", node.courses, [
        ["course_name", "课程"], ["course_code", "代码"],
        ["credits", "学分"], ["study_status", "修读状态"],
      ]);
      detail.appendChild(courses);
    }
    group.appendChild(detail);
    if (node.children?.length) renderRequirementTree(detail, node.children);
  }
}

// 问答依据中的平面节点也使用树形展示，保留原始字段供完整依据查看。
function flatRequirementTree(nodes) {
  const entries = new Map();
  for (const node of nodes) {
    const key = node.node_id ?? node.source_node_id;
    if (!key || entries.has(key)) throw new Error("培养计划节点标识异常");
    entries.set(key, { ...node, children: [] });
  }
  const roots = [];
  for (const [key, node] of entries) {
    const visited = new Set();
    let current = key;
    while (current != null) {
      if (visited.has(current) || !entries.has(current) || visited.size >= 50) {
        throw new Error("培养计划父子关系异常");
      }
      visited.add(current);
      const entry = entries.get(current);
      current = entry.parent_id ?? entry.parent_source_id ?? null;
    }
    const parent = node.parent_id ?? node.parent_source_id ?? null;
    (parent == null ? roots : entries.get(parent).children).push(node);
  }
  return roots;
}

async function managementRequest(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 75000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail?.message || `请求失败（HTTP ${response.status}）`);
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("等待超时，尚不能确定操作结果。确认导入可重试同一预览，不会重复执行已完成的确认。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

const uploadForm = document.getElementById("import-form");
const uploadType = document.getElementById("import-type");
const uploadFile = document.getElementById("import-file");
const previewButton = document.getElementById("preview-button");
const confirmButton = document.getElementById("confirm-button");
const previewContainer = document.getElementById("import-preview");
const importMessage = document.getElementById("import-message");
let activePreview = null;
let importBusy = false;

function setImportBusy(value) {
  importBusy = value;
  uploadType.disabled = value;
  uploadFile.disabled = value;
  previewButton.disabled = value;
  confirmButton.disabled = value || !activePreview;
}

function invalidatePreview() {
  activePreview = null;
  confirmButton.disabled = true;
  previewContainer.replaceChildren();
  importMessage.textContent = "请上传新文件并重新预览。";
}

uploadType.addEventListener("change", () => {
  invalidatePreview();
  uploadFile.value = "";
  uploadFile.accept = { grades: ".xlsx", schedule: ".json,.pdf", requirements: ".html,.htm" }[uploadType.value];
});
uploadFile.addEventListener("change", invalidatePreview);

function showPreview(preview, source = "手动导入") {
  previewContainer.replaceChildren();
  addText(previewContainer, "p", `本次预览来源：${source}`);
  addText(previewContainer, "p", `文件：${preview.filename}；预览到期：${new Date(preview.expires_at).toLocaleString()}`);
  addText(previewContainer, "p", `解析概况：${JSON.stringify(preview.summary)}`);
  for (const warning of preview.warnings) addText(previewContainer, "p", warning);
  const payload = preview.payload;
  if (preview.data_type === "grades") {
    showTable(previewContainer, "成绩预览", payload, [
      ["academic_year", "学年"], ["semester", "学期"], ["course_name", "课程"],
      ["score_raw", "原始成绩"], ["credits", "学分"], ["exam_nature", "考试性质"], ["is_void", "是否作废"],
    ]);
  } else if (preview.data_type === "requirements") {
    renderRequirementTree(previewContainer, flatRequirementTree(payload));
  } else {
    const rows = [];
    for (const course of payload.courses) {
      if (!course.meetings.length) {
        rows.push({ course_name: course.course_name, credits: course.credits, weekday: "时间未明确" });
      }
      for (const meeting of course.meetings) {
        rows.push({ ...meeting, course_name: course.course_name, credits: course.credits,
          periods: `${meeting.period_start}—${meeting.period_end}`, weeks_text: meeting.weeks.join("、") });
      }
    }
    showTable(previewContainer, "课表预览（星期1为周一，5为周五）", rows, [
      ["course_name", "课程"], ["credits", "学分"], ["teaching_type", "环节"],
      ["weekday", "星期"], ["periods", "节次"], ["weeks_text", "周次"], ["location", "地点"],
    ]);
  }
  const details = document.createElement("details");
  addText(details, "summary", "查看完整预览与文件哈希");
  addText(details, "pre", JSON.stringify(preview, null, 2));
  previewContainer.appendChild(details);
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (importBusy) return;
  const file = uploadFile.files[0];
  invalidatePreview();
  if (!file || file.size === 0 || file.size > 10 * 1024 * 1024) {
    importMessage.textContent = "请选择不超过10MB的非空文件。";
    return;
  }
  setImportBusy(true);
  importMessage.textContent = "正在解析，尚未写入学业数据库……";
  try {
    const preview = await managementRequest(`/api/v1/imports/preview?data_type=${uploadType.value}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) }, body: file,
    });
    showPreview(preview);
    activePreview = preview;
    importMessage.textContent = "预览通过，尚未入库。核对无误后点击确认导入。";
  } catch (error) {
    invalidatePreview();
    importMessage.textContent = error.message;
  } finally {
    setImportBusy(false);
  }
});

confirmButton.addEventListener("click", async () => {
  if (importBusy || !activePreview) return;
  if (!window.confirm("确认预览中的学期和数据正确，并导入数据库？")) return;
  setImportBusy(true);
  importMessage.textContent = "正在导入数据库……";
  try {
    const result = await managementRequest(`/api/v1/imports/${activePreview.preview_id}/confirm`, { method: "POST" });
    const labels = { created: "新快照已创建", unchanged: "内容未变化，沿用已有快照" };
    const outcome = labels[result.result.status] || `新增${result.result.inserted}条，更新${result.result.updated}条，未变化${result.result.unchanged}条`;
    importMessage.textContent = `${outcome}\n确认时间：${new Date(result.confirmed_at).toLocaleString()}\n${result.note}`;
    addText(previewContainer, "pre", JSON.stringify(result, null, 2));
    activePreview = null;
    await Promise.allSettled([refreshData(), refreshPlan()]);
  } catch (error) {
    importMessage.textContent = error.message;
  } finally {
    setImportBusy(false);
  }
});

async function refreshData() {
  const container = document.getElementById("data-status");
  container.textContent = "正在读取数据库……";
  try {
    const data = await managementRequest("/api/v1/data/status");
    container.replaceChildren();
    const types = { grades: "成绩", schedule: "课表", requirements: "培养计划" };
    const rows = data.items.map((item) => ({ ...item, type_label: types[item.data_type],
      time_label: item.imported_at ? new Date(item.imported_at).toLocaleString() : "未提供" }));
    showTable(container, "已导入数据", rows, [["type_label", "类型"], ["academic_year", "学年"],
      ["semester", "学期"], ["records", "成绩记录数"], ["snapshot_id", "快照"], ["time_label", "数据库数据时间"]]);
    addText(container, "p", data.note);
  } catch (error) { container.textContent = error.message; }
}

async function refreshPlan() {
  const container = document.getElementById("plan-tree");
  container.textContent = "正在读取培养计划……";
  try {
    const data = await managementRequest("/api/v1/data/requirements");
    container.replaceChildren();
    if (data.imported_at) addText(container, "p", `导入时间：${new Date(data.imported_at).toLocaleString()}`);
    addText(container, "p", data.note);
    renderRequirementTree(container, data.tree);
  } catch (error) { container.textContent = error.message; }
}

async function refreshTasks() {
  const container = document.getElementById("task-list");
  container.textContent = "正在读取采集日志……";
  try {
    const data = await managementRequest("/api/v1/collections/tasks");
    container.replaceChildren();
    const labels = { started: "已开始，未见结束记录", validated: "采集校验通过（未代表入库）", failed: "失败", cancelled: "已取消" };
    const rows = data.items.map((item) => ({ ...item, status_label: labels[item.status] || item.status,
      time_label: item.recorded_at ? new Date(item.recorded_at).toLocaleString() : "未提供",
      counts_label: item.parsed_counts ? JSON.stringify(item.parsed_counts) : "未解析" }));
    showTable(container, "最近采集任务", rows, [["data_type", "数据类型"], ["academic_year", "学年"], ["semester", "学期"],
      ["status_label", "状态"], ["stage", "阶段"], ["counts_label", "解析数量"], ["error_type", "错误类型"], ["time_label", "日志时间"]]);
    addText(container, "p", data.note);
    if (data.malformed_lines) addText(container, "p", `有${data.malformed_lines}行损坏日志未展示。`);
    const details = document.createElement("details");
    addText(details, "summary", "查看任务ID、原始文件路径与哈希");
    addText(details, "pre", JSON.stringify(data.items, null, 2));
    container.appendChild(details);
  } catch (error) { container.textContent = error.message; }
}

document.getElementById("refresh-data").addEventListener("click", refreshData);
document.getElementById("refresh-plan").addEventListener("click", refreshPlan);
document.getElementById("refresh-tasks").addEventListener("click", refreshTasks);
document.addEventListener("academic:navigation", event => {
  const refresh = { "data-panel": refreshData, "plan-panel": refreshPlan, "tasks-panel": refreshTasks }[event.detail.panelId];
  if (refresh) refresh();
});
