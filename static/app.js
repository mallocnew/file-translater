"use strict";

const STORAGE_KEY = "folio.settings";

const els = {
  keyState: document.getElementById("keyState"),
  drop: document.getElementById("drop"),
  file: document.getElementById("file"),
  fileCard: document.getElementById("fileCard"),
  fileName: document.getElementById("fileName"),
  fileMeta: document.getElementById("fileMeta"),
  replaceFile: document.getElementById("replaceFile"),
  clearFile: document.getElementById("clearFile"),
  sourceLang: document.getElementById("sourceLang"),
  targetLang: document.getElementById("targetLang"),
  model: document.getElementById("model"),
  customModel: document.getElementById("customModel"),
  modelId: document.getElementById("modelId"),
  modelHint: document.getElementById("modelHint"),
  glossary: document.getElementById("glossary"),
  instructions: document.getElementById("instructions"),
  start: document.getElementById("start"),
  stop: document.getElementById("stop"),
  status: document.getElementById("status"),
  error: document.getElementById("error"),
  stageEyebrow: document.getElementById("stageEyebrow"),
  stageTitle: document.getElementById("stageTitle"),
  stageActions: document.getElementById("stageActions"),
  progress: document.getElementById("progress"),
  placeholder: document.getElementById("placeholder"),
  resultScroll: document.getElementById("resultScroll"),
  result: document.getElementById("result"),
  copyBtn: document.getElementById("copyBtn"),
  mdBtn: document.getElementById("mdBtn"),
  docxBtn: document.getElementById("docxBtn"),
  sourceBtn: document.getElementById("sourceBtn"),
};

const state = {
  config: null,
  token: null,
  stem: "document",
  running: false,
  text: "",
  sourceView: false,
  finished: false,
  controller: null,
  fileSeq: 0,
};

init();

async function init() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("配置加载失败");
    state.config = await response.json();
  } catch (error) {
    showError(error.message || "配置加载失败");
    return;
  }
  fillLanguages();
  fillModels();
  loadSettings();
  bind();
  refreshModelHint();
  refreshKeyState();
  refreshStart();
  saveSettings();
}

function fillLanguages() {
  const languages = state.config.languages;
  addOption(els.sourceLang, "自动检测", "自动检测");
  languages.forEach((language) => {
    addOption(els.sourceLang, language, language);
    addOption(els.targetLang, language, language);
  });
  els.targetLang.value = "简体中文";
}

function fillModels() {
  state.config.models.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.label + (item.id === "qwen-long" ? " · 推荐" : "");
    els.model.appendChild(option);
  });
  const custom = document.createElement("option");
  custom.value = "__custom__";
  custom.textContent = "自定义模型";
  els.model.appendChild(custom);
  els.model.value = "qwen-long";
}

function bind() {
  ["glossary", "instructions", "modelId"].forEach((id) => {
    els[id].addEventListener("input", onSettingsChanged);
  });
  ["sourceLang", "targetLang", "model"].forEach((id) => {
    els[id].addEventListener("change", onSettingsChanged);
  });
  els.file.addEventListener("change", () => {
    if (els.file.files[0]) useFile(els.file.files[0]);
  });
  els.replaceFile.addEventListener("click", () => els.file.click());
  els.clearFile.addEventListener("click", clearFile);
  ["dragenter", "dragover"].forEach((name) => {
    els.drop.addEventListener(name, (event) => {
      event.preventDefault();
      els.drop.classList.add("hot");
    });
  });
  els.drop.addEventListener("dragleave", () => els.drop.classList.remove("hot"));
  els.drop.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    els.drop.classList.remove("hot");
    if (event.dataTransfer.files[0]) useFile(event.dataTransfer.files[0]);
  });
  document.addEventListener("dragover", (event) => {
    if ([...event.dataTransfer.types].includes("Files")) event.preventDefault();
  });
  document.addEventListener("drop", (event) => {
    if (!event.dataTransfer.files || !event.dataTransfer.files.length) return;
    event.preventDefault();
    useFile(event.dataTransfer.files[0]);
  });
  els.start.addEventListener("click", startTranslation);
  els.stop.addEventListener("click", stopTranslation);
  els.copyBtn.addEventListener("click", copyText);
  els.mdBtn.addEventListener("click", downloadMarkdown);
  els.docxBtn.addEventListener("click", downloadDocx);
  els.sourceBtn.addEventListener("click", toggleSource);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      els.start.click();
    }
  });
}

function onSettingsChanged() {
  els.customModel.hidden = els.model.value !== "__custom__";
  refreshModelHint();
  refreshStart();
  saveSettings();
}

function currentSpec() {
  if (els.model.value === "__custom__") return null;
  return state.config.models.find((item) => item.id === els.model.value) || null;
}

function currentModelId() {
  if (els.model.value === "__custom__") return els.modelId.value.trim();
  return els.model.value;
}

function refreshModelHint() {
  const spec = currentSpec();
  els.modelHint.textContent = spec
    ? spec.hint
    : "填写能直接阅读 PDF 和 Word 的模型 ID，调用方式与 Qwen-Long 相同。";
  els.customModel.hidden = els.model.value !== "__custom__";
}

function refreshKeyState() {
  const ready = Boolean(state.config.has_server_key);
  const host = state.config.endpoint_host || "";
  els.keyState.textContent = ready
    ? (host ? `后台已配置 · ${host}` : "后台已配置")
    : "后台还没有配置密钥";
  els.keyState.classList.toggle("ready", ready);
}

function refreshStart() {
  const hasModel = Boolean(currentModelId());
  els.start.disabled = state.running || !state.token || !state.config.has_server_key || !hasModel;
}

function loadSettings() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch (_error) {
    saved = {};
  }
  if (saved.source) els.sourceLang.value = saved.source;
  if (saved.target) els.targetLang.value = saved.target;
  if (saved.glossary) els.glossary.value = saved.glossary;
  if (saved.instructions) els.instructions.value = saved.instructions;
  if (saved.model && state.config.models.some((item) => item.id === saved.model)) {
    els.model.value = saved.model;
  }
  els.customModel.hidden = els.model.value !== "__custom__";
}

function saveSettings() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    source: els.sourceLang.value,
    target: els.targetLang.value,
    glossary: els.glossary.value,
    instructions: els.instructions.value,
    model: currentModelId(),
  }));
}

async function useFile(file) {
  const seq = ++state.fileSeq;
  stopTranslation();
  clearError();
  const suffix = (file.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
  if (![".pdf", ".doc", ".docx"].includes(suffix)) {
    showError("请上传 PDF、DOC 或 DOCX");
    return;
  }
  const maxBytes = state.config.max_upload_mb * 1024 * 1024;
  if (file.size > maxBytes) {
    showError(`文件超过 ${state.config.max_upload_mb} MB`);
    return;
  }
  forgetToken();
  resetResult();
  state.stem = file.name.replace(/\.[^.]+$/, "") || "document";
  els.fileName.textContent = file.name;
  els.fileMeta.textContent = "正在接收文件…";
  els.drop.hidden = true;
  els.fileCard.hidden = false;
  els.stageTitle.textContent = file.name;
  els.stageEyebrow.textContent = "译文";
  setStatus("正在接收文件");
  const body = new FormData();
  body.append("file", file, file.name);
  try {
    const response = await fetch("/api/prepare", { method: "POST", body });
    const payload = await readJson(response);
    if (seq !== state.fileSeq) return;
    if (!response.ok) throw new Error(payload.detail || "文件接收失败");
    state.token = payload.token;
    state.stem = payload.stem || state.stem;
    els.fileMeta.textContent = `${formatSize(payload.size)} · ${payload.kind.toUpperCase()}`;
    setStatus("");
    refreshStart();
  } catch (error) {
    if (seq !== state.fileSeq) return;
    showError(error.message || "文件接收失败");
    els.fileMeta.textContent = "接收失败";
  }
}

function clearFile() {
  state.fileSeq += 1;
  stopTranslation();
  forgetToken();
  els.file.value = "";
  els.fileCard.hidden = true;
  els.drop.hidden = false;
  els.stageTitle.textContent = "还没有文档";
  els.stageEyebrow.textContent = "译文";
  resetResult();
  setStatus("");
  clearError();
  refreshStart();
}

function forgetToken() {
  if (!state.token) return;
  fetch(`/api/prepare/${state.token}`, { method: "DELETE" });
  state.token = null;
}

function resetResult() {
  state.text = "";
  state.finished = false;
  state.sourceView = false;
  els.result.replaceChildren();
  els.resultScroll.hidden = true;
  els.placeholder.hidden = false;
  els.stageActions.hidden = true;
  els.progress.hidden = true;
  els.progress.classList.remove("run");
  els.sourceBtn.textContent = "源码";
}

async function startTranslation() {
  if (els.start.disabled || state.running || !state.token) return;
  clearError();
  state.running = true;
  state.finished = false;
  state.text = "";
  state.sourceView = false;
  els.stop.hidden = false;
  els.stageActions.hidden = true;
  els.placeholder.hidden = true;
  els.resultScroll.hidden = false;
  els.progress.hidden = false;
  els.progress.classList.add("run");
  els.result.replaceChildren();
  refreshStart();
  setStatus("正在连接模型");
  const controller = new AbortController();
  state.controller = controller;
  saveSettings();
  try {
    const response = await fetch(`/api/translate/${state.token}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: currentModelId(),
        target_lang: els.targetLang.value,
        source_lang: els.sourceLang.value,
        glossary: els.glossary.value,
        instructions: els.instructions.value,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload = await readJson(response);
      throw new Error(payload.detail || `请求失败 ${response.status}`);
    }
    await readSSE(response, handleEvent);
  } catch (error) {
    if (error.name === "AbortError") {
      finishPartial("已停止，可以下载已译出的部分");
      return;
    }
    showError(error.message || "翻译失败");
    finishPartial("翻译中断");
  } finally {
    state.running = false;
    state.controller = null;
    els.stop.hidden = true;
    els.progress.classList.remove("run");
    refreshStart();
  }
}

function stopTranslation() {
  if (state.controller) state.controller.abort();
}

function handleEvent(event) {
  if (event.type === "status") {
    setStatus(event.message || "");
    return;
  }
  if (event.type === "token") {
    appendText(event.text || "");
    return;
  }
  if (event.type === "done") {
    if (typeof event.text === "string") state.text = event.text;
    state.finished = true;
    renderResult();
    els.stageActions.hidden = !state.text;
    const usage = formatUsage(event);
    setStatus(usage ? `译完 · ${usage}` : "译完");
    return;
  }
  if (event.type === "cancelled") {
    finishPartial("已停止，可以下载已译出的部分");
    return;
  }
  if (event.type === "error") {
    showError(event.message || "翻译失败");
    finishPartial("翻译中断");
  }
}

function appendText(chunk) {
  state.text += chunk;
  const box = els.resultScroll;
  const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 90;
  let live = document.getElementById("live");
  if (!live || state.finished) {
    els.result.replaceChildren();
    live = document.createElement("pre");
    live.id = "live";
    live.className = "live";
    els.result.appendChild(live);
  }
  live.textContent = state.text;
  if (stick) box.scrollTop = box.scrollHeight;
}

function finishPartial(message) {
  if (!state.text) {
    els.resultScroll.hidden = true;
    els.placeholder.hidden = false;
    els.progress.hidden = true;
    setStatus(message);
    return;
  }
  state.finished = true;
  renderResult();
  els.stageActions.hidden = false;
  setStatus(message);
}

function renderResult() {
  if (state.sourceView) {
    const pre = document.createElement("pre");
    pre.className = "live";
    pre.textContent = state.text;
    els.result.replaceChildren(pre);
    return;
  }
  const article = document.createElement("article");
  article.className = "prose";
  article.innerHTML = renderMarkdown(state.text);
  els.result.replaceChildren(article);
}

function toggleSource() {
  state.sourceView = !state.sourceView;
  els.sourceBtn.textContent = state.sourceView ? "排版" : "源码";
  if (state.text) renderResult();
}

async function copyText() {
  try {
    await navigator.clipboard.writeText(state.text);
  } catch (_error) {
    const area = document.createElement("textarea");
    area.value = state.text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  const previous = els.copyBtn.textContent;
  els.copyBtn.textContent = "已复制";
  setTimeout(() => { els.copyBtn.textContent = previous; }, 1200);
}

function downloadMarkdown() {
  const blob = new Blob([state.text], { type: "text/markdown;charset=utf-8" });
  downloadBlob(blob, `${safeName(state.stem)}-${els.targetLang.value}.md`);
}

async function downloadDocx() {
  els.docxBtn.disabled = true;
  try {
    const filename = `${safeName(state.stem)}-${els.targetLang.value}.docx`;
    const response = await fetch("/api/export/docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: state.text, filename }),
    });
    if (!response.ok) {
      const payload = await readJson(response);
      throw new Error(payload.detail || "导出 Word 失败");
    }
    downloadBlob(await response.blob(), filename);
  } catch (error) {
    showError(error.message || "导出 Word 失败");
  } finally {
    els.docxBtn.disabled = false;
  }
}

async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    parts.forEach((part) => dispatchSSE(part, onEvent));
  }
  if (buffer.trim()) dispatchSSE(buffer, onEvent);
}

function dispatchSSE(part, onEvent) {
  if (!part.trim() || part.startsWith(":")) return;
  let type = "message";
  let data = "";
  part.split("\n").forEach((line) => {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  });
  if (!data) return;
  onEvent(JSON.parse(data));
}

function renderMarkdown(source) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let index = 0;
  while (index < lines.length) {
    const stripped = lines[index].trim();
    if (!stripped) {
      index += 1;
      continue;
    }
    if (stripped.startsWith("```")) {
      const body = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      html += `<pre><code>${escapeHtml(body.join("\n"))}</code></pre>`;
      continue;
    }
    const heading = stripped.match(/^(#{1,6})\s+(\S.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length, 4);
      html += `<h${level}>${inline(heading[2])}</h${level}>`;
      index += 1;
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(stripped)) {
      index += 1;
      continue;
    }
    if (isTable(stripped)) {
      const rows = [];
      while (index < lines.length && isTable(lines[index].trim())) {
        if (!isSeparator(lines[index].trim())) rows.push(splitRow(lines[index].trim()));
        index += 1;
      }
      if (rows.length) {
        html += "<table><tbody>";
        rows.forEach((row, rowIndex) => {
          html += "<tr>";
          row.forEach((cell) => {
            const tag = rowIndex === 0 ? "th" : "td";
            html += `<${tag}>${inline(cell)}</${tag}>`;
          });
          html += "</tr>";
        });
        html += "</tbody></table>";
      }
      continue;
    }
    const list = stripped.match(/^([-*]|\d+\.)\s+(.+)$/);
    if (list) {
      const ordered = /^\d+\./.test(stripped);
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>`;
      while (index < lines.length) {
        const item = lines[index].trim().match(ordered ? /^\d+\.\s+(.+)$/ : /^[-*]\s+(.+)$/);
        if (!item) break;
        html += `<li>${inline(item[1])}</li>`;
        index += 1;
      }
      html += `</${tag}>`;
      continue;
    }
    if (stripped.startsWith(">")) {
      const quoted = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoted.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      html += `<blockquote class="quote"><p>${inline(joinLines(quoted))}</p></blockquote>`;
      continue;
    }
    const paragraph = [stripped];
    index += 1;
    while (index < lines.length && lines[index].trim() && !startsBlock(lines[index].trim())) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    html += `<p>${inline(joinLines(paragraph))}</p>`;
  }
  return html;
}

function startsBlock(stripped) {
  return stripped.startsWith("```")
    || /^(#{1,6})\s+\S/.test(stripped)
    || /^(-{3,}|\*{3,}|_{3,})$/.test(stripped)
    || isTable(stripped)
    || /^([-*]|\d+\.)\s+/.test(stripped)
    || stripped.startsWith(">");
}

function isTable(stripped) {
  return stripped.startsWith("|") && stripped.endsWith("|") && stripped.slice(1, -1).includes("|");
}

function isSeparator(stripped) {
  return splitRow(stripped).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitRow(stripped) {
  return stripped.replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function joinLines(lines) {
  const parts = lines.filter(Boolean);
  if (!parts.length) return "";
  return parts.slice(1).reduce((text, line) => {
    if (text.at(-1).charCodeAt(0) < 128 && line.charCodeAt(0) < 128) return `${text} ${line}`;
    return text + line;
  }, parts[0]);
}

function inline(text) {
  const escaped = escapeHtml(text);
  const codes = [];
  const withCode = escaped.replace(/`([^`]+)`/g, (_all, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });
  const formatted = withCode
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return formatted.replace(/\u0000(\d+)\u0000/g, (_all, index) => `<code>${codes[index]}</code>`);
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function formatUsage(event) {
  const input = Number(event.input_tokens || 0);
  const output = Number(event.output_tokens || 0);
  if (!input && !output) return "";
  return `输入 ${input.toLocaleString("zh-CN")} tokens · 输出 ${output.toLocaleString("zh-CN")} tokens`;
}

function formatSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function safeName(name) {
  return (name || "document").replace(/[\\/:*?"<>|]+/g, "_").slice(0, 80);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function setStatus(text) {
  els.status.textContent = text;
}

function showError(text) {
  els.error.hidden = false;
  els.error.textContent = text;
}

function clearError() {
  els.error.hidden = true;
  els.error.textContent = "";
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return {};
  }
}

function addOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
}
