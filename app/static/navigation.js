// 各功能独立展示，保留已有DOM与任务状态，支持刷新、直达及浏览器前进后退。
const viewNames = { "question-panel": "问答首页", "import-panel": "数据导入",
  "data-panel": "数据时间", "calendar-panel": "开学日期同步", "plan-panel": "培养计划", "tasks-panel": "采集任务" };
let visibleView = null;

function showAcademicView(panelId) {
  if (!Object.hasOwn(viewNames, panelId)) panelId = "question-panel";
  document.querySelectorAll(".app-view").forEach(view => { view.hidden = view.id !== panelId; });
  document.querySelectorAll(".function-list a").forEach(link => {
    if (link.hash === `#${panelId}`) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = `${viewNames[panelId]} · 个人学业 Agent`;
  if (visibleView !== panelId) {
    visibleView = panelId;
    document.dispatchEvent(new CustomEvent("academic:navigation", { detail: { panelId } }));
  }
}

function navigateToPanel(panelId) {
  if (!Object.hasOwn(viewNames, panelId)) return;
  if (location.hash !== `#${panelId}`) history.pushState(null, "", `#${panelId}`);
  showAcademicView(panelId);
}

document.querySelectorAll(".function-list a").forEach(link => {
  link.addEventListener("click", event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigateToPanel(link.hash.slice(1));
  });
});
function restoreAcademicView() { showAcademicView(location.hash.slice(1)); }
window.addEventListener("hashchange", restoreAcademicView);
window.addEventListener("popstate", restoreAcademicView);
document.addEventListener("DOMContentLoaded", restoreAcademicView);
