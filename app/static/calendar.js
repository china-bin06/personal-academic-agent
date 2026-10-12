const clockElement = document.getElementById("site-clock");
const calendarForm = document.getElementById("calendar-form");
const calendarMessage = document.getElementById("calendar-message");
const calendarButton = document.getElementById("calendar-save");
let clockAnchor = null;
let clockStart = 0;
let calendarDirty = false;
let calendarLoading = false;

function tickSchoolClock() {
  const timestamp = clockAnchor == null ? Date.now() : clockAnchor + performance.now() - clockStart;
  const date = new Date(timestamp);
  clockElement.dateTime = date.toISOString();
  clockElement.textContent = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric",
    month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
  clockElement.title = clockAnchor == null ? "北京时间（浏览器时钟；尚未同步服务端）" : "北京时间（已同步服务端）";
}

function displayCalendar(status, fill = true) {
  clockAnchor = new Date(status.current_time).getTime();
  clockStart = performance.now();
  tickSchoolClock();
  const config = status.configuration;
  if (fill && !calendarDirty && config) {
    document.getElementById("calendar-year").value = config.academic_year;
    document.getElementById("calendar-semester").value = String(config.semester);
    document.getElementById("calendar-monday").value = config.first_monday;
    document.getElementById("calendar-weeks").value = config.teaching_weeks;
  }
  if (!calendarDirty) calendarMessage.textContent = config
    ? `已同步：${config.academic_year}第${config.semester}学期；第一教学周周一 ${config.first_monday}；共${config.teaching_weeks}周。\n保存时间：${new Date(config.updated_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}（北京时间）\n${status.note}`
    : "尚未同步开学日期。请确认学校校历后填写并保存，再查询日期课表。";
}

async function refreshCalendar() {
  if (calendarLoading) return;
  calendarLoading = true;
  try { displayCalendar(await managementRequest("/api/v1/calendar")); }
  catch (error) { if (!calendarDirty) calendarMessage.textContent = error.message; }
  finally { calendarLoading = false; }
}

calendarForm.addEventListener("input", () => { calendarDirty = true; });
calendarForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (calendarButton.disabled) return;
  const params = { academic_year: document.getElementById("calendar-year").value.trim(),
    semester: Number(document.getElementById("calendar-semester").value),
    first_monday: document.getElementById("calendar-monday").value,
    teaching_weeks: Number(document.getElementById("calendar-weeks").value) };
  const match = /^(\d{4})-(\d{4})$/.exec(params.academic_year);
  if (!match || Number(match[2]) !== Number(match[1]) + 1) {
    calendarMessage.textContent = "学年必须为连续两年，例如2026-2027。";
    return;
  }
  if (new Date(`${params.first_monday}T00:00:00Z`).getUTCDay() !== 1) {
    calendarMessage.textContent = "请填写第一教学周的周一日期，不是报到日。";
    return;
  }
  if (!window.confirm(`确认当前学期是${params.academic_year}第${params.semester}学期，第一教学周周一为${params.first_monday}，教学周范围为${params.teaching_weeks}周？`)) return;
  calendarButton.disabled = true;
  calendarMessage.textContent = "正在保存日期配置……";
  try {
    const status = await managementRequest("/api/v1/calendar", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(params) });
    calendarDirty = false;
    displayCalendar(status);
  } catch (error) { calendarMessage.textContent = error.message; }
  finally { calendarButton.disabled = false; }
});

const illustrationSize = document.getElementById("illustration-size");
function resizeIllustration(value) {
  const size = Math.max(160, Math.min(360, Number(value) || 240));
  illustrationSize.value = String(size);
  document.documentElement.style.setProperty("--campus-width", `${size}px`);
}
try { resizeIllustration(localStorage.getItem("academic:illustration-size")); } catch { resizeIllustration(240); }
illustrationSize.addEventListener("input", () => {
  resizeIllustration(illustrationSize.value);
  try { localStorage.setItem("academic:illustration-size", illustrationSize.value); } catch { /* 仍支持当前页面调整 */ }
});
document.addEventListener("academic:navigation", event => {
  if (event.detail.panelId === "calendar-panel") refreshCalendar();
});
tickSchoolClock();
setInterval(tickSchoolClock, 1000);
setInterval(refreshCalendar, 60000);
refreshCalendar();
