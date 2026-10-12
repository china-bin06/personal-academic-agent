// 页面采集控制独立于原有问答与文件上传流程。
const collectionForm = document.getElementById("collection-form");
const collectionType = document.getElementById("collection-type");
const collectionYear = document.getElementById("collection-year");
const collectionSemester = document.getElementById("collection-semester");
const collectionStart = document.getElementById("collection-start");
const collectionContinue = document.getElementById("collection-continue");
const collectionCancel = document.getElementById("collection-cancel");
const collectionPreview = document.getElementById("collection-preview");
const collectionMessage = document.getElementById("collection-message");
const collectionLabels = { starting: "启动中", running: "采集中", waiting_login: "等待手动登录",
  cancelling: "等待取消完成", completed: "采集完成，尚未代表入库", failed: "采集失败", cancelled: "已取消" };
let selectedCollection = null;
let collectionRequestBusy = false;
let collectionTimer = null;
let autoCollectionPreview = false;
let collectionPollBusy = false;

function collectionActive(state) {
  return state && !["completed", "failed", "cancelled"].includes(state.status);
}

function syncCollectionControls() {
  const active = collectionActive(selectedCollection);
  collectionStart.disabled = collectionRequestBusy || active;
  collectionType.disabled = collectionRequestBusy || active;
  collectionYear.disabled = collectionRequestBusy || active;
  collectionSemester.disabled = collectionRequestBusy || active;
  collectionContinue.hidden = selectedCollection?.status !== "waiting_login";
  collectionContinue.disabled = collectionRequestBusy;
  collectionCancel.hidden = !active;
  collectionCancel.disabled = collectionRequestBusy || selectedCollection?.status === "cancelling";
  collectionPreview.hidden = selectedCollection?.status !== "completed";
  collectionPreview.disabled = collectionRequestBusy;
  const term = collectionType.value !== "requirements";
  document.getElementById("collection-term").hidden = !term;
  collectionYear.required = term;
}

function displayCollection(state) {
  selectedCollection = state;
  collectionMessage.textContent = `${collectionLabels[state.status]} · ${state.stage}\n${state.message}\n任务：${state.task_id}${state.error_type ? `；错误类型：${state.error_type}` : ""}`;
  syncCollectionControls();
}

async function refreshCollectionJobs() {
  const jobs = await managementRequest("/api/v1/collections/jobs");
  const container = document.getElementById("collection-jobs");
  container.replaceChildren();
  showTable(container, "页面采集任务", jobs.map(job => ({ ...job, status_label: collectionLabels[job.status] })), [
    ["data_type", "类型"], ["academic_year", "学年"], ["semester", "学期"],
    ["status_label", "状态"], ["stage", "阶段"], ["message", "说明"],
  ]);
  return jobs;
}

async function loadCollectionPreview() {
  if (!selectedCollection || selectedCollection.status !== "completed") return;
  if (importBusy) throw new Error("上传或导入正在执行，请完成后再查看采集预览。");
  if (activePreview && !window.confirm("替换当前未确认的预览，显示采集文件？")) return;
  setImportBusy(true);
  try {
    const preview = await managementRequest(`/api/v1/collections/jobs/${selectedCollection.task_id}/preview`, { method: "POST" });
    showPreview(preview, "自动导入（教务平台采集）");
    activePreview = preview;
    importMessage.textContent = "采集文件预览通过，尚未入库。请核对后确认导入。";
    navigateToPanel("import-panel");
    document.getElementById("import-review").scrollIntoView({ behavior: "smooth" });
  } finally {
    setImportBusy(false);
  }
}

async function pollCollection() {
  if (collectionPollBusy) return;
  collectionPollBusy = true;
  clearTimeout(collectionTimer);
  try {
    if (!selectedCollection) return;
    const taskId = selectedCollection.task_id;
    const state = await managementRequest(`/api/v1/collections/jobs/${taskId}`);
    if (selectedCollection?.task_id !== taskId) return;
    displayCollection(state);
    if (!collectionActive(state)) {
      await Promise.allSettled([refreshCollectionJobs(), refreshTasks()]);
      if (state.status === "completed" && autoCollectionPreview && !importBusy && !activePreview) {
        autoCollectionPreview = false;
        await loadCollectionPreview();
      }
    }
  } catch (error) {
    collectionMessage.textContent = error.message + "\n页面连接失败不会自动取消后台任务，请恢复连接或刷新页面查看。";
  } finally {
    collectionPollBusy = false;
    if (collectionActive(selectedCollection)) collectionTimer = setTimeout(pollCollection, 1500);
  }
}

collectionType.addEventListener("change", syncCollectionControls);
collectionForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (collectionRequestBusy || collectionActive(selectedCollection)) return;
  const payload = { data_type: collectionType.value };
  if (payload.data_type !== "requirements") {
    payload.academic_year = collectionYear.value.trim();
    payload.semester = Number(collectionSemester.value);
    const match = /^(\d{4})-(\d{4})$/.exec(payload.academic_year);
    if (!match || Number(match[2]) !== Number(match[1]) + 1) {
      collectionMessage.textContent = "请输入连续两年的学年，例如2026-2027。";
      return;
    }
  }
  collectionRequestBusy = true;
  syncCollectionControls();
  try {
    const state = await managementRequest("/api/v1/collections/jobs", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    displayCollection(state);
    autoCollectionPreview = true;
    await pollCollection();
  } catch (error) { collectionMessage.textContent = error.message; }
  finally { collectionRequestBusy = false; syncCollectionControls(); }
});

async function collectionAction(action) {
  if (collectionRequestBusy || !selectedCollection) return;
  collectionRequestBusy = true;
  syncCollectionControls();
  collectionMessage.textContent = action === "continue"
    ? "正在提交继续采集请求，随后检查教务登录状态……"
    : "正在提交取消请求……";
  try {
    displayCollection(await managementRequest(`/api/v1/collections/jobs/${selectedCollection.task_id}/${action}`, { method: "POST" }));
  } catch (error) { collectionMessage.textContent = error.message; }
  finally { collectionRequestBusy = false; syncCollectionControls(); }
}
collectionContinue.addEventListener("click", () => collectionAction("continue"));
collectionCancel.addEventListener("click", () => collectionAction("cancel"));
collectionPreview.addEventListener("click", async () => {
  if (collectionRequestBusy) return;
  collectionRequestBusy = true;
  syncCollectionControls();
  try { await loadCollectionPreview(); }
  catch (error) { collectionMessage.textContent = error.message; }
  finally { collectionRequestBusy = false; syncCollectionControls(); }
});
document.getElementById("refresh-tasks").addEventListener("click", async () => {
  try { await refreshCollectionJobs(); if (selectedCollection) await pollCollection(); }
  catch (error) { collectionMessage.textContent = error.message; }
});

async function restoreCollection() {
  try {
    const jobs = await refreshCollectionJobs();
    const state = jobs.find(collectionActive) || jobs[0];
    if (state) { displayCollection(state); if (collectionActive(state)) await pollCollection(); }
  } catch (error) { collectionMessage.textContent = error.message; }
}
syncCollectionControls();
restoreCollection();
document.addEventListener("academic:navigation", event => {
  if (event.detail.panelId === "tasks-panel") {
    refreshCollectionJobs().catch(error => { collectionMessage.textContent = error.message; });
  }
});
