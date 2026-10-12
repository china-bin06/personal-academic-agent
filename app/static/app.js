const form = document.getElementById("question-form");
const questionInput = document.getElementById("question");
const submitButton = document.getElementById("submit-button");
const result = document.getElementById("result");
const resultTitle = document.getElementById("result-title");
const answer = document.getElementById("answer");
const warnings = document.getElementById("warnings");
const evidenceContainer = document.getElementById("evidence");
let busy = false;

function addText(parent, tag, text) {
  const element = document.createElement(tag);
  element.textContent = String(text ?? "");
  parent.appendChild(element);
  return element;
}

function clearResult() {
  answer.textContent = "";
  warnings.replaceChildren();
  evidenceContainer.replaceChildren();
}

function showResponse(data) {
  const titles = {
    answered: "回答",
    needs_clarification: "需要补充信息",
    failed: "查询未完成",
  };
  resultTitle.textContent = titles[data.status];
  answer.textContent = data.answer;
  for (const warning of data.warnings) addText(warnings, "li", warning);
  if (data.status === "needs_clarification") {
    addText(warnings, "li", "请把补充条件和原问题合并，重新提交完整问题。");
  }
  for (const item of data.evidence) renderEvidence(item);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const question = questionInput.value.trim();
  if (!question) {
    questionInput.focus();
    return;
  }

  busy = true;
  submitButton.disabled = true;
  submitButton.textContent = "正在查询……";
  clearResult();
  result.hidden = false;
  resultTitle.textContent = "处理中";
  answer.textContent = "正在查询已导入数据，请稍候。";
  const controller = new AbortController();
  // 后端总超时为60秒，浏览器保留额外响应时间。
  const timeout = setTimeout(() => controller.abort(), 75000);

  try {
    const response = await fetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (
      !["answered", "needs_clarification", "failed"].includes(data.status)
      || typeof data.answer !== "string"
      || !Array.isArray(data.warnings)
      || !Array.isArray(data.evidence)
    ) throw new Error("响应格式不符合接口约定");
    clearResult();
    showResponse(data);
  } catch (error) {
    clearResult();
    resultTitle.textContent = "请求失败";
    answer.textContent = error.name === "AbortError"
      ? "等待响应超时。请稍后重新提交完整问题。"
      : "无法取得有效响应。请检查后端服务，并在浏览器 Network 中查看请求状态。";
  } finally {
    clearTimeout(timeout);
    busy = false;
    submitButton.disabled = false;
    submitButton.textContent = "提交问题";
  }
});

document.querySelectorAll("#examples button").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.textContent.trim();
    questionInput.focus();
  });
});

function showTable(parent, title, rows, columns) {
  addText(parent, "h3", title);
  if (!Array.isArray(rows) || rows.length === 0) {
    addText(parent, "p", "没有可展示的记录。");
    return;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const [, label] of columns) addText(headRow, "th", label);
  head.appendChild(headRow);
  table.appendChild(head);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const [key] of columns) addText(tr, "td", row[key] ?? "未提供");
    body.appendChild(tr);
  }
  table.appendChild(body);
  wrapper.appendChild(table);
  parent.appendChild(wrapper);
}

function renderGrade(parent, data, title = "成绩汇总") {
  showTable(parent, title, [data], [
    ["academic_year", "学年"], ["semester", "学期"],
    ["included_records", "纳入记录数"], ["average", "平均分"],
    ["median", "中位数"], ["maximum", "最高分"], ["minimum", "最低分"],
  ]);
  const columns = [
    ["course_name", "课程"], ["course_code", "课程代码"], ["score", "分数"],
  ];
  showTable(parent, "最高分课程", data.highest_courses, columns);
  showTable(parent, "最低分课程", data.lowest_courses, columns);
  addText(parent, "p", `成绩来源：${(data.source_files || []).join("、") || "未提供"}`);
  addText(parent, "p", data.rule || "");
}

function renderEvidence(item) {
  const card = document.createElement("section");
  evidenceContainer.appendChild(card);
  const names = {
    get_grade_summary: "成绩查询依据", compare_terms: "学期比较依据",
    get_schedule: "课表查询依据", get_degree_progress: "学分进度依据",
    get_schedule_for_date: "日期课表查询依据",
  };
  addText(card, "h3", names[item.tool] || "查询依据");
  const displayArguments = { ...item.arguments };
  delete displayArguments.lowest_count;
  addText(card, "p", `查询条件：${JSON.stringify(displayArguments)}`);
  const data = item.data;
  if (item.tool === "get_grade_summary") {
    renderGrade(card, data);
  } else if (item.tool === "compare_terms") {
    renderGrade(card, data.first, "第一个学期");
    renderGrade(card, data.second, "第二个学期");
    addText(card, "p", `平均分差值：${data.average_difference ?? "无法计算"}`);
  } else if (item.tool === "get_schedule" || item.tool === "get_schedule_for_date") {
    if (item.tool === "get_schedule_for_date") {
      addText(card, "p", `日期：${data.target_date}（北京时间）；${data.academic_year ?? "学期未配置"}第${data.semester ?? "—"}学期；第${data.week ?? "—"}教学周`);
    }
    const weekdays = ["", "一", "二", "三", "四", "五", "六", "日"];
    const rows = data.items.map((item) => ({
      ...item,
      weekday_label: `星期${weekdays[item.weekday]}`,
      periods: `${item.period_start}—${item.period_end}`,
    }));
    showTable(card, "上课安排", rows, [
      ["course_name", "课程"], ["teaching_type", "教学环节"],
      ["weekday_label", "星期"], ["periods", "节次"], ["location", "地点"],
    ]);
    if (data.unscheduled_courses.length > 0) {
      addText(card, "p", `时间未明确的课程：${data.unscheduled_courses.join("、")}`);
    }
  } else if (item.tool === "get_degree_progress") {
    renderRequirementTree(card, flatRequirementTree(data.nodes));
    addText(card, "p", "类别可能存在父子关系，不能把所有行的学分直接相加。");
  }
  if (data.note) addText(card, "p", data.note);
  if (data.source_note) addText(card, "p", `来源说明：${data.source_note}`);
  if (data.imported_at) addText(card, "p", `数据导入时间：${data.imported_at}`);
  const details = document.createElement("details");
  addText(details, "summary", "查看完整查询依据");
  addText(details, "pre", JSON.stringify(item, null, 2));
  card.appendChild(details);
}

async function checkServices() {
  const label = document.getElementById("service-status");
  try {
    const backend = await fetch("/health");
    if (!backend.ok) throw new Error("backend unavailable");
    const database = await fetch("/health/db");
    label.textContent = database.ok
      ? "后端与数据库健康检查通过；模型连接状态以实际问答为准。"
      : "后端可用，数据库健康检查未通过。";
  } catch {
    label.textContent = "无法完成服务健康检查，请检查后端是否运行。";
  }
}

checkServices();
