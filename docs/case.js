/* ClaimBack-AI case-flow screen (M2b-fix1). Vanilla JS, no build, no external scripts. */
"use strict";

const S = {
  caseId: null,
  caseView: null,
  readings: [],
  review: null,
  drafts: null,
  pkg: null,
  selectedEx: null,
  serverOk: false,
  running: false,
  runGen: 0,
  putting: false,
  redactions: null,
  segments: null,
};

const AGENTS = [
  { group: "Forensic Visual", desc: "증거 접수와 목록 정리" },
  { group: "Fact-Timeline Chronology", desc: "증거 읽기와 사실 정리" },
  { group: "Financial Auditor", desc: "계산과 숫자 대조" },
  { group: "Judicial Form Filler", desc: "서류 묶음 만들기" },
];

const STATE_KO = {
  INTAKE: "접수",
  READING: "판독 중",
  ORGANIZING: "사실 정리 중",
  CHECKPOINT_1: "사실 확인 대기",
  CALCULATING: "계산 중",
  DRAFTING: "문안 작성 중",
  VERIFYING: "검증 중",
  DRAFT_APPROVAL: "문안 승인 대기",
  PACKAGING: "편철 중",
  CHECKPOINT_2: "최종 확인",
  HOLD: "보류",
};

const STATE_ORDER = [
  "INTAKE", "READING", "ORGANIZING", "CHECKPOINT_1", "CALCULATING",
  "DRAFTING", "VERIFYING", "DRAFT_APPROVAL", "PACKAGING", "CHECKPOINT_2",
];

const STATUS_KO = {
  waiting: "대기",
  running: "실행 중",
  done: "완료",
  hold: "보류",
  skipped: "건너뜀",
};

const TAG_KO = {
  loan_request: "빌려 달라는 말",
  amount_mention: "금액 언급",
  repay_promise: "갚겠다는 말",
  reminder: "갚아 달라는 말",
  other: "기타",
};

const GATE_KO = {
  G1a: "숫자·이름은 슬롯으로만",
  G1b: "최종 서류 검사",
  G3: "문장마다 증거 표시",
  G2: "필수 칸 확인",
  G4: "금액 범위 확인",
  NAMING: "금지 표현 검사",
  DRAFT: "문안 규칙 검사",
};

const ROLE_OPTIONS = [
  ["loan_transfer", "대여 이체"],
  ["repayment", "변제 입금"],
  ["loan_agreement", "차용증"],
  ["other", "기타"],
];

const KNOWN_ROLES = new Set(ROLE_OPTIONS.map(([val]) => val));

function $(id) {
  return document.getElementById(id);
}

function setStatus(msg, kind) {
  const el = $("status-line");
  el.textContent = msg || "";
  el.classList.toggle("is-neutral", kind === "neutral");
}

function errText(data) {
  if (data && data.detail) {
    if (typeof data.detail === "string") return data.detail;
    let msg = data.detail.message || "";
    const miss = data.detail.missing_requirements;
    if (Array.isArray(miss) && miss.length > 0) {
      msg += ` (필요: ${miss.join(", ")})`;
    }
    return msg;
  }
  return "";
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  return { ok: res.ok, status: res.status, data };
}

function fmtLatency(ms) {
  return (ms / 1000).toFixed(1) + "초";
}

function fmtDateDots(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso || "";
  return `${m[1]}. ${Number(m[2])}. ${Number(m[3])}.`;
}

function exLabel(exId) {
  const m = /^EX(\d+)$/.exec(exId || "");
  return m ? `갑 제${m[1]}호증` : exId;
}

function sentenceNo(sid) {
  const m = /^s(\d+)$/.exec(sid || "");
  return m ? `문장 ${Number(m[1])}` : `문장 ${sid}`;
}

function gateName(g) {
  return GATE_KO[g] || g;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- boot ---------- */

document.addEventListener("DOMContentLoaded", () => {
  $("btn-sample").addEventListener("click", loadSample);
  $("btn-run").addEventListener("click", runCase);
  $("btn-delete").addEventListener("click", deleteCase);
  $("btn-confirm").addEventListener("click", confirmFacts);
  $("btn-approve-continue").addEventListener("click", approveAndContinue);
  $("upload-input").addEventListener("change", uploadFiles);
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => copyBlock(btn.dataset.copy, btn));
  });
  checkServer();
});

async function checkServer() {
  try {
    const res = await fetch("/health", { cache: "no-store" });
    if (!res.ok) throw new Error("bad");
    S.serverOk = true;
    $("offline-notice").hidden = true;
    $("app").hidden = false;
  } catch {
    S.serverOk = false;
    $("offline-notice").hidden = false;
    $("app").hidden = true;
  }
}

function revealSection(sectionId, titleId) {
  $(sectionId).hidden = false;
  const t = titleId ? $(titleId) : null;
  if (t) {
    t.focus({ preventScroll: true });
    const reduce = window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    t.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
  }
}

/* ---------- case lifecycle ---------- */

function setRunningUI(on) {
  for (const id of ["btn-sample", "btn-run", "btn-confirm", "btn-approve-continue", "btn-delete"]) {
    const el = $(id);
    if (!el) continue;
    if (id === "btn-run" || id === "btn-delete") {
      el.disabled = on || !S.caseId;
    } else {
      el.disabled = on;
    }
  }
}

async function loadSample() {
  if (S.running || S.putting) return;
  setStatus("");
  const res = await api("POST", "/api/cases/sample", { set: "kr" });
  if (!res.ok) {
    setStatus("사건을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  resetCaseState(res.data);
  renderCaseMeta();
  renderBoard();
  $("btn-delete").disabled = false;
  const ran = await runWithPolling();
  if (ran && S.caseView && S.caseView.state === "CHECKPOINT_1") {
    await loadCheckpoint1();
  }
}

function resetCaseState(view) {
  S.caseId = view.case_id;
  S.caseView = view;
  S.readings = [];
  S.review = null;
  S.drafts = null;
  S.pkg = null;
  S.selectedEx = null;
  S.redactions = null;
  S.segments = null;
}

async function runCase() {
  if (!S.caseId || S.running || S.putting) return;
  setStatus("");
  const ran = await runWithPolling();
  if (!ran || !S.caseView) return;
  await openStagesForState();
}

async function openStagesForState() {
  const st = S.caseView && S.caseView.state;
  if (!st) return;
  const at = (s) => STATE_ORDER.indexOf(st) >= STATE_ORDER.indexOf(s);
  if (at("CHECKPOINT_1")) await loadCheckpoint1({ reveal: st === "CHECKPOINT_1" });
  if (at("DRAFT_APPROVAL")) await loadDrafts({ reveal: st === "DRAFT_APPROVAL" });
  if (st === "CHECKPOINT_2") await loadPackage({ reveal: true });
}

async function runWithPolling() {
  if (S.running) return false;
  S.running = true;
  const gen = ++S.runGen;
  setRunningUI(true);
  $("run-progress").hidden = false;
  const poll = async () => {
    if (gen !== S.runGen || !S.running) return;
    try {
      const res = await api("GET", `/api/cases/${S.caseId}`);
      if (gen !== S.runGen || !S.running) return;
      if (res.ok) {
        S.caseView = res.data;
        renderCaseMeta();
        renderBoard();
      }
    } catch {
      /* a failed poll must not stop the run; the final fetch decides */
    }
    if (gen === S.runGen && S.running) setTimeout(poll, 500);
  };
  setTimeout(poll, 500);
  try {
    const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
    if (gen !== S.runGen) return false;
    if (!res.ok) {
      setStatus("실행하지 못했습니다. " + errText(res.data));
    } else {
      S.caseView = res.data;
    }
  } finally {
    if (gen === S.runGen) {
      S.running = false;
      setRunningUI(false);
      $("run-progress").hidden = true;
    }
  }
  if (gen !== S.runGen) return false;
  const cur = await api("GET", `/api/cases/${S.caseId}`);
  if (gen !== S.runGen) return false;
  if (cur.ok) S.caseView = cur.data;
  renderCaseMeta();
  renderBoard();
  return true;
}

async function deleteCase() {
  if (!S.caseId || S.running) return;
  const res = await api("DELETE", `/api/cases/${S.caseId}`);
  if (!res.ok && res.status !== 404) {
    setStatus("삭제하지 못했습니다. " + errText(res.data));
    return;
  }
  S.caseId = null;
  S.caseView = null;
  S.readings = [];
  S.review = null;
  S.drafts = null;
  S.pkg = null;
  S.selectedEx = null;
  S.redactions = null;
  S.segments = null;
  $("btn-delete").disabled = true;
  $("btn-run").disabled = true;
  for (const id of ["board-section", "checkpoint-section", "calc-section",
    "drafts-section", "package-section"]) {
    $(id).hidden = true;
  }
  document.querySelector(".case-meta").hidden = true;
  $("stub-banner").hidden = true;
  $("replay-badge").hidden = true;
  setStatus("사건을 삭제했습니다.", "neutral");
}

async function uploadFiles(ev) {
  const files = ev.target.files;
  if (!files || files.length === 0) return;
  if (!S.caseId) {
    const created = await api("POST", "/api/cases", { jurisdiction: "KR" });
    if (!created.ok) {
      setStatus("사건을 만들지 못했습니다. " + errText(created.data));
      return;
    }
    resetCaseState(created.data);
    $("btn-delete").disabled = false;
  }
  const form = new FormData();
  for (const f of files) form.append("files", f);
  try {
    const res = await fetch(`/api/cases/${S.caseId}/evidence`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus("올리지 못했습니다. " + errText(data));
      return;
    }
    S.caseView = data;
    renderCaseMeta();
    renderBoard();
    setStatus("");
  } catch {
    setStatus("올리지 못했습니다.");
  }
  ev.target.value = "";
}

/* ---------- board ---------- */

function renderCaseMeta() {
  const v = S.caseView;
  if (!v) return;
  document.querySelector(".case-meta").hidden = false;
  $("case-id").textContent = v.case_id;
  const st = $("case-state");
  st.textContent = STATE_KO[v.state] || v.state;
  st.setAttribute("data-state", v.state);
  $("stub-banner").hidden = !v.stub;
  $("replay-badge").hidden = v.meta_mode !== "replay";
  $("board-section").hidden = false;
  $("btn-run").disabled = S.running || !S.caseId;
  $("btn-delete").disabled = S.running || !S.caseId;
}

function stepOrder(v, s) {
  return v.steps.indexOf(s) + 1;
}

function modelBadgeText(s) {
  const base = s.model || "규칙";
  if (s.key === "reading" && s.substeps && s.substeps.length > 0) {
    const n = s.substeps.filter((x) => x.status === "done").length;
    return `${base} · 판독 ${n}건`;
  }
  return base;
}

function countModelCalls(v) {
  let calls = 0;
  for (const s of (v.steps || [])) {
    if (!s.model) continue;
    if ((s.key === "reading" || s.key === "vision")
      && Array.isArray(s.substeps) && s.substeps.length > 0) {
      calls += s.substeps.filter((x) => x && x.status === "done").length;
    } else {
      calls += Number(s.attempts || 0);
    }
  }
  return calls;
}

function renderBoardSummary(v) {
  const el = $("board-summary");
  const calls = countModelCalls(v);
  const cost = v.run_cost_usd || "0";
  const mode = v.meta_mode === "replay" ? "(재생)" : "실제 호출";
  el.textContent = `Meta 모델 호출 ${calls}회 · $${cost} · ${mode}`;
  el.dataset.calls = String(calls);
}

function renderBoard() {
  const v = S.caseView;
  if (!v) return;
  renderHold(v);
  renderBoardSummary(v);
  const board = $("agent-board");
  board.innerHTML = "";
  for (const a of AGENTS) {
    const steps = v.steps.filter((s) => s.group === a.group);
    if (steps.length === 0) continue;
    const card = document.createElement("div");
    card.className = "agent-card";
    card.dataset.testid = `agent-card-${a.group}`;
    const h = document.createElement("h3");
    h.textContent = a.group;
    card.appendChild(h);
    const d = document.createElement("p");
    d.className = "agent-desc";
    d.textContent = a.desc;
    card.appendChild(d);
    for (const s of steps) {
      const row = document.createElement("div");
      row.className = "step-row" + (s.status === "skipped" ? " is-skipped" : "")
        + (s.status === "running" ? " is-running" : "");
      row.dataset.testid = `step-${s.key}`;
      row.dataset.status = s.status;
      const head = document.createElement("div");
      head.className = "step-head";
      const order = document.createElement("span");
      order.className = "step-order";
      order.textContent = String(stepOrder(v, s));
      head.appendChild(order);
      const agent = document.createElement("span");
      agent.className = "step-agent";
      agent.textContent = s.agent;
      head.appendChild(agent);
      const model = document.createElement("span");
      model.className = "model-badge";
      model.textContent = modelBadgeText(s);
      head.appendChild(model);
      const st = document.createElement("span");
      st.className = "step-status";
      st.dataset.status = s.status;
      st.textContent = STATUS_KO[s.status] || s.status;
      head.appendChild(st);
      if (s.status !== "waiting" && s.status !== "skipped") {
        const meta = document.createElement("span");
        meta.className = "step-meta";
        meta.textContent = v.meta_mode === "replay"
          ? `$${s.cost_usd || "0"}`
          : `${fmtLatency(s.latency_ms || 0)} · $${s.cost_usd || "0"}`;
        head.appendChild(meta);
      }
      row.appendChild(head);
      const noteText = s.status === "skipped"
        ? "이 버전에서는 사용하지 않음"
        : (s.note || "");
      if (noteText) {
        const note = document.createElement("div");
        note.className = "step-note";
        note.textContent = noteText;
        row.appendChild(note);
      }
      if (s.substeps && s.substeps.length > 0) {
        const ul = document.createElement("ul");
        ul.className = "substeps";
        for (const sub of s.substeps) {
          const li = document.createElement("li");
          li.textContent = v.meta_mode === "replay"
            ? `${exLabel(sub.ex_id)} · ${STATUS_KO[sub.status] || sub.status}`
            : `${exLabel(sub.ex_id)} · ${STATUS_KO[sub.status] || sub.status} · ${fmtLatency(sub.latency_ms || 0)}`;
          ul.appendChild(li);
        }
        row.appendChild(ul);
      }
      card.appendChild(row);
    }
    board.appendChild(card);
  }
  renderUserStrip(v);
}

function renderUserStrip(v) {
  const strip = $("user-strip");
  strip.innerHTML = "";
  const users = v.steps.filter((s) => s.group === "User");
  if (users.length === 0) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;
  const label = document.createElement("span");
  label.className = "user-strip-label";
  label.textContent = "사용자 확인";
  strip.appendChild(label);
  for (const s of users) {
    const chip = document.createElement("span");
    chip.className = "user-chip";
    chip.dataset.testid = `step-${s.key}`;
    chip.dataset.status = s.status;
    const label = s.status === "running" ? "확인 기다림" : (STATUS_KO[s.status] || s.status);
    chip.textContent = `${stepOrder(v, s)}. ${s.agent} · ${label}`;
    strip.appendChild(chip);
  }
}

function renderHold(v) {
  const box = $("hold-box");
  const list = $("hold-list");
  list.innerHTML = "";
  const reasons = v.hold_reasons || [];
  box.hidden = reasons.length === 0;
  reasons.forEach((r, i) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.testid = `hold-check-${i}`;
    const msgText = r.code === "replay_fixture_missing"
      ? "기록된 응답이 없는 입력입니다"
      : (r.message || r.code || "");
    check.setAttribute("aria-label", `보류 사유 확인: ${msgText}`);
    label.appendChild(check);
    const msg = document.createElement("span");
    msg.textContent = " " + msgText;
    label.appendChild(msg);
    li.appendChild(label);
    list.appendChild(li);
  });
}

/* ---------- checkpoint 1 ---------- */

async function loadCheckpoint1(opts) {
  const [rd, rv, red, seg] = await Promise.all([
    api("GET", `/api/cases/${S.caseId}/readings`),
    api("GET", `/api/cases/${S.caseId}/review`),
    api("GET", `/api/cases/${S.caseId}/redactions`),
    api("GET", `/api/cases/${S.caseId}/segments`),
  ]);
  if (!rd.ok || !rv.ok) {
    setStatus("사실 확인 자료를 불러오지 못했습니다.");
    return;
  }
  S.readings = rd.data;
  S.review = rv.data;
  S.redactions = red.ok ? red.data : null;
  S.segments = seg.ok ? seg.data : null;
  renderCheckpoint();
  revealSection("checkpoint-section", opts && opts.reveal === false ? null : "checkpoint-title");
}

function readingsFor(exId) {
  const r = (S.readings || []).find((x) => x.ex_id === exId);
  return r ? r.items : [];
}

function readingSide(exId, itemId) {
  const items = readingsFor(exId);
  const it = items.find((x) => x.item_id === itemId);
  return it ? it.side : null;
}

function redactionPreviewUrl(exId) {
  const previews = S.redactions && S.redactions.previews;
  if (!Array.isArray(previews)) return null;
  const p = previews.find((x) => x && x.ex_id === exId);
  return p ? p.url : null;
}

function segmentsFor(exId) {
  if (!Array.isArray(S.segments)) return [];
  const entry = S.segments.find((x) => x && x.ex_id === exId);
  if (!entry || !Array.isArray(entry.objects)) return [];
  return entry.objects.filter((o) => o && o.box && o.box.ref_w && o.box.ref_h);
}

function renderCheckpoint() {
  renderEvidenceList();
  const first = (S.caseView.evidence.find((e) => e.preview_url) || S.caseView.evidence[0]);
  if (first) selectEvidence(first.ex_id);
  renderFields();
  renderConflicts();
  renderUtterances();
  renderRoles();
}

function renderEvidenceList() {
  const ul = $("evidence-list");
  ul.innerHTML = "";
  for (const e of S.caseView.evidence) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.testid = `evidence-${e.ex_id}`;
    btn.setAttribute("aria-pressed", S.selectedEx === e.ex_id ? "true" : "false");
    const evStatus = { ok: "읽음", hold: "보류", skipped: "건너뜀" }[e.status] || e.status;
    btn.textContent = `${e.label} · ${(e.sha256 || "").slice(0, 8)} · ${evStatus}`;
    btn.addEventListener("click", () => selectEvidence(e.ex_id));
    li.appendChild(btn);
    ul.appendChild(li);
  }
}

function selectEvidence(exId) {
  S.selectedEx = exId;
  renderEvidenceList();
  const e = S.caseView.evidence.find((x) => x.ex_id === exId);
  const img = $("viewer-img");
  const layer = $("box-layer");
  const empty = $("viewer-empty");
  layer.innerHTML = "";
  $("viewer-title").textContent = e ? e.label : "증거 보기";
  $("viewer-meta").textContent = e ? `${(e.sha256 || "").slice(0, 8)} · ${e.filename}` : "";
  const items = readingsFor(exId);
  if (!e || !e.preview_url) {
    img.hidden = true;
    img.removeAttribute("src");
    empty.hidden = false;
    empty.textContent = "미리보기가 없습니다.";
    $("reading-note").textContent = "";
    const legend = $("segment-legend");
    if (legend) legend.hidden = true;
    renderRedaction(exId);
    return;
  }
  empty.hidden = true;
  img.hidden = false;
  img.src = e.preview_url;
  if (items.length === 0) {
    $("reading-note").textContent = "판독 결과 없음";
    renderSegments(exId, layer);
    renderRedaction(exId);
    return;
  }
  $("reading-note").textContent = `판독 ${items.length}개`;
  for (const item of items) {
    const box = item.box;
    if (!box || !box.ref_w || !box.ref_h) continue;
    const div = document.createElement("div");
    div.className = "reading-box";
    div.dataset.testid = `reading-box-${exId}-${item.item_id}`;
    div.style.left = (box.x1 / box.ref_w * 100) + "%";
    div.style.top = (box.y1 / box.ref_h * 100) + "%";
    div.style.width = (Math.max(box.x2 - box.x1, 1) / box.ref_w * 100) + "%";
    div.style.height = (Math.max(box.y2 - box.y1, 1) / box.ref_h * 100) + "%";
    div.title = item.text_verbatim || "";
    layer.appendChild(div);
  }
  renderSegments(exId, layer);
  renderRedaction(exId);
}

function renderSegments(exId, layer) {
  const legend = $("segment-legend");
  const objs = segmentsFor(exId);
  if (legend) legend.hidden = objs.length === 0;
  for (const o of objs) {
    const box = o.box;
    const div = document.createElement("div");
    div.className = "segment-box";
    div.dataset.testid = `segment-box-${exId}`;
    div.style.left = (box.x1 / box.ref_w * 100) + "%";
    div.style.top = (box.y1 / box.ref_h * 100) + "%";
    div.style.width = (Math.max(box.x2 - box.x1, 1) / box.ref_w * 100) + "%";
    div.style.height = (Math.max(box.y2 - box.y1, 1) / box.ref_h * 100) + "%";
    div.title = o.target || "";
    layer.appendChild(div);
  }
}

function renderRedaction(exId) {
  const col = $("redaction-col");
  const img = $("redaction-img");
  if (!col || !img) return;
  const url = redactionPreviewUrl(exId);
  if (!url) {
    col.hidden = true;
    img.removeAttribute("src");
    return;
  }
  col.hidden = false;
  img.src = url;
}

function blinkBox(exId, itemId) {
  selectEvidence(exId);
  requestAnimationFrame(() => {
    const el = document.querySelector(`[data-testid="reading-box-${exId}-${itemId}"]`);
    if (el) {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
  });
}

function displayHint(f) {
  if (!f.display) return null;
  if (typeof f.value === "string" && f.display === f.value) return null;
  const hint = document.createElement("span");
  hint.className = "display-hint";
  hint.dataset.testid = `display-field-${f.field}`;
  hint.textContent = f.display;
  return hint;
}

function renderFields() {
  const body = $("fields-body");
  body.innerHTML = "";
  for (const f of S.review.fields) {
    const tr = document.createElement("tr");
    const th = document.createElement("td");
    th.textContent = f.label + (f.conflict ? " (충돌)" : "");
    tr.appendChild(th);
    const tdVal = document.createElement("td");
    if (f.field === "repayments" && Array.isArray(f.value)) {
      const rows = f.value.length > 0 ? f.value : [{ date: "", amount: "" }];
      rows.forEach((r, i) => {
        const wrap = document.createElement("div");
        const d = document.createElement("input");
        d.type = "date";
        d.value = r.date || "";
        d.dataset.testid = `field-repayments-${i}-date`;
        d.setAttribute("aria-label", `받은 돈 ${i + 1} 날짜`);
        const a = document.createElement("input");
        a.type = "text";
        a.value = r.amount || "";
        a.dataset.testid = `field-repayments-${i}-amount`;
        a.setAttribute("aria-label", `받은 돈 ${i + 1} 금액`);
        wrap.appendChild(d);
        wrap.appendChild(a);
        const aErr = document.createElement("span");
        aErr.className = "field-error";
        aErr.dataset.testid = `error-field-repayments-${i}-amount`;
        aErr.hidden = true;
        wrap.appendChild(aErr);
        tdVal.appendChild(wrap);
      });
      const hint = displayHint(f);
      if (hint) tdVal.appendChild(hint);
    } else if (f.field === "transaction_kind") {
      const sel = document.createElement("select");
      sel.dataset.testid = "field-transaction_kind";
      sel.setAttribute("aria-label", f.label);
      for (const [val, label] of [["civil", "개인 간 거래"], ["commercial", "사업 거래"]]) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = label;
        if (f.value === val) opt.selected = true;
        sel.appendChild(opt);
      }
      tdVal.appendChild(sel);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.value = f.value ?? "";
      input.dataset.testid = `field-${f.field}`;
      input.setAttribute("aria-label", f.label);
      tdVal.appendChild(input);
      const hint = displayHint(f);
      if (hint) tdVal.appendChild(hint);
      if (AMOUNT_FIELDS.has(f.field)) {
        const err = document.createElement("span");
        err.className = "field-error";
        err.dataset.testid = `error-field-${f.field}`;
        err.hidden = true;
        tdVal.appendChild(err);
      }
    }
    tr.appendChild(tdVal);
    const tdSrc = document.createElement("td");
    for (const src of (f.sources || [])) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "source-chip";
      chip.dataset.testid = `source-chip-${f.field}-${src.ex_id}-${src.item_id}`;
      chip.textContent = exLabel(src.ex_id);
      chip.addEventListener("click", () => blinkBox(src.ex_id, src.item_id));
      tdSrc.appendChild(chip);
    }
    tr.appendChild(tdSrc);
    body.appendChild(tr);
  }
}

function conflictText(c) {
  if (typeof c === "string") return c || null;
  if (c && typeof c === "object" && !Array.isArray(c)) {
    const labels = {};
    for (const f of ((S.review && S.review.fields) || [])) labels[f.field] = f.label || f.field;
    let names = "";
    if (Array.isArray(c.fields)) {
      names = c.fields.map((f) => labels[f] || f).join(", ");
    } else if (typeof c.fields === "string") {
      names = c.fields;
    }
    const note = c.note || c.message || "";
    if (names && note) return `${names}: ${note}`;
    return note || names || null;
  }
  return null;
}

function renderConflicts() {
  const ul = $("conflict-list");
  ul.innerHTML = "";
  const items = [];
  for (const c of ((S.review && S.review.conflicts) || [])) {
    const t = conflictText(c);
    if (t) items.push(t);
  }
  for (const q of ((S.review && S.review.questions) || [])) items.push(q.question || `${q.field} 입력 필요`);
  if (items.length === 0) {
    const li = document.createElement("li");
    li.textContent = "없음";
    ul.appendChild(li);
    return;
  }
  for (const t of items) {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  }
}

function speakerLabel(u) {
  if (u.speaker !== null && u.speaker !== undefined && u.speaker !== "" && u.speaker !== "null") {
    return u.speaker;
  }
  const side = readingSide(u.ex_id, u.item_id);
  if (side === "right") return "오른쪽 말풍선";
  if (side === "left") return "왼쪽 말풍선";
  return "말한 사람 모름";
}

function exNum(exId) {
  const m = /^EX(\d+)$/.exec(exId || "");
  return m ? Number(m[1]) : 0;
}

function itemNum(itemId) {
  const m = /(\d+)/.exec(itemId || "");
  return m ? Number(m[1]) : 0;
}

function firstRepayPromiseKey() {
  const promised = (S.review.utterances || []).filter((u) => (u.tags || []).includes("repay_promise"));
  promised.sort((a, b) => (exNum(a.ex_id) - exNum(b.ex_id)) || (itemNum(a.item_id) - itemNum(b.item_id)));
  return promised.length > 0 ? `${promised[0].ex_id}:${promised[0].item_id}` : null;
}

function renderUtterances() {
  const ul = $("utterance-list");
  ul.innerHTML = "";
  const firstPromise = firstRepayPromiseKey();
  for (const u of (S.review.utterances || [])) {
    const li = document.createElement("li");
    li.dataset.testid = `utterance-${u.ex_id}-${u.item_id}`;
    li.dataset.tags = (u.tags || []).join(" ");
    const who = speakerLabel(u);
    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.testid = `highlight-${u.ex_id}-${u.item_id}`;
    check.setAttribute("aria-label", `강조: ${who}: ${u.text}`);
    if (firstPromise === `${u.ex_id}:${u.item_id}`) check.checked = true;
    label.appendChild(check);
    li.appendChild(label);
    const body = document.createElement("span");
    body.textContent = `${who}: ${u.text} `;
    li.appendChild(body);
    for (const tag of (u.tags || [])) {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = TAG_KO[tag] || tag;
      li.appendChild(chip);
    }
    ul.appendChild(li);
  }
}

function renderRoles() {
  const ul = $("role-list");
  ul.innerHTML = "";
  for (const r of (S.review.evidence_roles || [])) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.textContent = `${exLabel(r.ex_id)} `;
    const sel = document.createElement("select");
    sel.dataset.testid = `role-${r.ex_id}`;
    sel.setAttribute("aria-label", `${exLabel(r.ex_id)} 역할`);
    const current = KNOWN_ROLES.has(r.suggested_role) ? r.suggested_role : "other";
    for (const [val, name] of ROLE_OPTIONS) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = name;
      if (current === val) opt.selected = true;
      sel.appendChild(opt);
    }
    label.appendChild(sel);
    li.appendChild(label);
    ul.appendChild(li);
  }
}

const DISPLAY_AMOUNT_RE = /^\s*\d[\d,]*\s*원?\s*$/;

function parseAmountInput(raw) {
  const t = String(raw ?? "").trim();
  if (t === "") return "";
  if (!DISPLAY_AMOUNT_RE.test(t)) return t;
  return t.replace(/[\s,원]/g, "");
}

const AMOUNT_FIELDS = new Set(["principal"]);

function gatherFacts() {
  const fields = {};
  for (const f of S.review.fields) {
    if (f.field === "repayments") {
      const rows = [];
      for (let i = 0; ; i++) {
        const d = document.querySelector(`[data-testid="field-repayments-${i}-date"]`);
        const a = document.querySelector(`[data-testid="field-repayments-${i}-amount"]`);
        if (!d || !a) break;
        if (d.value || a.value) rows.push({ date: d.value, amount: parseAmountInput(a.value) });
      }
      fields.repayments = rows;
    } else if (f.field === "transaction_kind") {
      fields[f.field] = document.querySelector('[data-testid="field-transaction_kind"]').value;
    } else {
      const el = document.querySelector(`[data-testid="field-${f.field}"]`);
      let val = el.value.trim();
      if (AMOUNT_FIELDS.has(f.field)) val = parseAmountInput(val);
      fields[f.field] = (val === "" && f.value === null) ? null : val;
    }
  }
  const evidence_roles = {};
  for (const r of (S.review.evidence_roles || [])) {
    evidence_roles[r.ex_id] = document.querySelector(`[data-testid="role-${r.ex_id}"]`).value;
  }
  const highlight = [];
  for (const u of (S.review.utterances || [])) {
    const el = document.querySelector(`[data-testid="highlight-${u.ex_id}-${u.item_id}"]`);
    if (el && el.checked) highlight.push(`${u.ex_id}:${u.item_id}`);
  }
  return { fields, evidence_roles, highlight, as_of: $("asof").value };
}

function clearFactsErrors() {
  document.querySelectorAll('[data-testid^="error-field-"]').forEach((el) => {
    el.hidden = true;
    el.textContent = "";
  });
}

function showFactsErrorsFor(msg) {
  if (!msg) return;
  if (msg.includes("principal")) {
    const el = document.querySelector('[data-testid="error-field-principal"]');
    if (el) {
      el.textContent = msg;
      el.hidden = false;
    }
  }
  if (msg.includes("repayments.amount")) {
    document.querySelectorAll('[data-testid^="error-field-repayments-"]').forEach((el) => {
      el.textContent = msg;
      el.hidden = false;
    });
  }
}

async function confirmFacts() {
  if (S.putting || S.running) return;
  setStatus("");
  clearFactsErrors();
  S.putting = true;
  $("btn-confirm").disabled = true;
  try {
    const body = gatherFacts();
    const put = await api("PUT", `/api/cases/${S.caseId}/facts`, body);
    if (!put.ok) {
      const msg = errText(put.data);
      setStatus("확정값을 저장하지 못했습니다. " + msg);
      if (put.status === 400) showFactsErrorsFor(msg);
      return;
    }
    S.caseView = put.data;
    renderCaseMeta();
    renderBoard();
  } finally {
    S.putting = false;
    $("btn-confirm").disabled = false;
  }
  await runWithPolling();
  if (S.caseView && S.caseView.state === "DRAFT_APPROVAL") {
    await loadDrafts();
  }
}

/* ---------- calculation + draft approval ---------- */

async function loadDrafts(opts) {
  const res = await api("GET", `/api/cases/${S.caseId}/drafts`);
  if (!res.ok) {
    setStatus("초안을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  S.drafts = res.data;
  renderCalc();
  renderDrafts();
  const reveal = !opts || opts.reveal !== false;
  $("calc-section").hidden = false;
  $("drafts-section").hidden = false;
  if (reveal) revealSection("calc-section", "calc-title");
}

function fmtWon(amountStr) {
  const n = Number(String(amountStr).split(".")[0]);
  if (!Number.isFinite(n)) return String(amountStr);
  return n.toLocaleString("ko-KR") + "원";
}

function renderCalc() {
  const calc = S.drafts.calculation;
  const ref = calc.reference_total || {};
  $("calc-title").textContent =
    `4. 입력한 사실 기준 계산(기준일 ${fmtDateDots(ref.as_of)})`;
  const body = $("alloc-body");
  body.innerHTML = "";
  for (const a of (calc.allocations || [])) {
    const tr = document.createElement("tr");
    for (const cell of [fmtDateDots(a.payment_date), fmtWon(a.payment_amount),
      fmtWon(a.applied_to_interest), fmtWon(a.applied_to_principal),
      fmtWon(a.remaining_principal_after)]) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  $("remaining-principal").textContent = fmtWon(calc.remaining_principal);
  $("accrual-start").textContent = fmtDateDots(calc.accrual_start_date);
  $("reference-total").textContent = ref.amount != null ? fmtWon(ref.amount) : "—";
  $("reference-asof").textContent = fmtDateDots(ref.as_of);
  const ol = $("calc-steps");
  ol.innerHTML = "";
  for (const s of (calc.calculation_steps || [])) {
    const li = document.createElement("li");
    li.textContent = `${s.label}: ${s.formula}`;
    ol.appendChild(li);
  }
}

function slotChips(text) {
  const frag = document.createDocumentFragment();
  const re = /\{\{([^}]*)\}\}/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    const chip = document.createElement("span");
    chip.className = "slot-chip";
    chip.textContent = `{{${m[1]}}}`;
    frag.appendChild(chip);
    last = m.index + m[0].length;
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  return frag;
}

function renderDrafts() {
  const d = S.drafts;
  const rev = $("revision-note");
  if (d.revisions && d.revisions.length > 0) {
    rev.hidden = false;
    rev.textContent = `문안 작성 → 검증 → 수정 ${d.revision_rounds}회`;
  } else {
    rev.hidden = true;
  }
  renderDraftsGateSummary();
  const list = $("sentence-list");
  list.innerHTML = "";
  for (const s of (d.sentences || [])) {
    list.appendChild(sentenceEl(s, d.gate_results || []));
  }
}

function showGate(g) {
  return !(g.gate === "G1b" && g.status === "skipped");
}

function gateRow(g) {
  const row = document.createElement("div");
  row.className = "gate-row";
  row.dataset.testid = `gate-${g.gate}`;
  row.dataset.gate = g.gate;
  row.dataset.status = g.status;
  const state = g.status === "pass" ? "✓ 통과"
    : g.status === "fail" ? "지적 있음"
    : g.status === "skipped" ? "건너뜀" : g.status;
  row.textContent = `${gateName(g.gate)} (${g.gate}): ${state}`;
  return row;
}

function sentenceEl(s, gateResults) {
  const box = document.createElement("div");
  box.className = "sentence";
  box.dataset.testid = `sentence-${s.sentence_id}`;
  box.dataset.sentenceType = s.type || "";

  const head = document.createElement("div");
  head.className = "sentence-head";
  const id = document.createElement("span");
  id.className = "sentence-id";
  id.textContent = sentenceNo(s.sentence_id);
  head.appendChild(id);
  for (const ex of (s.ex_refs || [])) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = ex === "USER" ? "(사용자 진술)" : `[${exLabel(ex)}]`;
    head.appendChild(tag);
  }
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.dataset.testid = `slots-toggle-${s.sentence_id}`;
  toggle.textContent = "슬롯 보기";
  head.appendChild(toggle);
  const editToggle = document.createElement("button");
  editToggle.type = "button";
  editToggle.dataset.testid = `edit-toggle-${s.sentence_id}`;
  editToggle.textContent = "고치기";
  head.appendChild(editToggle);
  box.appendChild(head);

  const rendered = document.createElement("p");
  rendered.className = "rendered-text";
  rendered.dataset.testid = `rendered-${s.sentence_id}`;
  rendered.textContent = s.rendered_text;
  box.appendChild(rendered);

  const slots = document.createElement("p");
  slots.className = "slots-view";
  slots.dataset.testid = `slots-${s.sentence_id}`;
  slots.hidden = true;
  slots.appendChild(slotChips(s.text_with_slots));
  box.appendChild(slots);
  toggle.addEventListener("click", () => {
    slots.hidden = !slots.hidden;
    rendered.hidden = !slots.hidden;
    toggle.textContent = slots.hidden ? "슬롯 보기" : "문장 보기";
  });

  const findings = document.createElement("div");
  findings.className = "findings";
  findings.dataset.testid = `findings-${s.sentence_id}`;
  box.appendChild(findings);
  renderFindings(findings, s, gateResults);

  const notice = document.createElement("p");
  notice.className = "sentence-notice";
  notice.dataset.testid = `notice-${s.sentence_id}`;
  notice.hidden = true;
  box.appendChild(notice);

  const edit = document.createElement("textarea");
  edit.dataset.testid = `edit-${s.sentence_id}`;
  edit.hidden = true;
  edit.value = s.text_with_slots;
  edit.setAttribute("aria-label", `${sentenceNo(s.sentence_id)} 고치기`);
  box.appendChild(edit);
  editToggle.addEventListener("click", () => {
    edit.hidden = !edit.hidden;
    editToggle.textContent = edit.hidden ? "고치기" : "접기";
  });

  const row = document.createElement("div");
  row.className = "row";
  const update = document.createElement("button");
  update.type = "button";
  update.dataset.testid = `update-${s.sentence_id}`;
  update.textContent = "다시 검사";
  row.appendChild(update);
  const approveLabel = document.createElement("label");
  approveLabel.className = "approve-label";
  const approve = document.createElement("input");
  approve.type = "checkbox";
  approve.dataset.testid = `approve-${s.sentence_id}`;
  approve.checked = !!s.approved;
  approve.disabled = (s.findings || []).length > 0;
  approve.setAttribute("aria-label", `${sentenceNo(s.sentence_id)} 승인`);
  approveLabel.appendChild(approve);
  approveLabel.appendChild(document.createTextNode(" 승인"));
  row.appendChild(approveLabel);
  box.appendChild(row);

  update.addEventListener("click", () => updateSentence(s.sentence_id));
  approve.addEventListener("change", () => approveSentence(s.sentence_id));
  return box;
}

function renderFindings(el, s, gateResults) {
  el.innerHTML = "";
  const mine = s.findings || [];
  if (mine.length === 0) {
    el.textContent = "지적 없음";
    el.dataset.status = "pass";
    el.classList.remove("is-bad");
    el.classList.add("is-ok");
    return;
  }
  el.dataset.status = "fail";
  el.classList.remove("is-ok");
  el.classList.add("is-bad");
  const byGate = {};
  for (const g of gateResults) {
    for (const f of (g.findings || [])) {
      if (f.sentence_id === s.sentence_id) {
        if (!byGate[g.gate]) byGate[g.gate] = [];
        byGate[g.gate].push(f);
      }
    }
  }
  const gates = Object.keys(byGate);
  const groups = gates.length > 0 ? gates : ["검사"];
  for (const gate of groups) {
    const line = document.createElement("div");
    line.dataset.gate = gate;
    const name = document.createElement("span");
    name.className = "gate-name";
    name.textContent = gate === "검사" ? "검사: " : `${gateName(gate)} (${gate}): `;
    line.appendChild(name);
    const items = byGate[gate] || mine;
    line.appendChild(document.createTextNode(
      items.map((f) => (f.fix_hint ? `${f.message} (${f.fix_hint})` : f.message)).join(" / ")));
    el.appendChild(line);
  }
}

function setDraftInputsDisabled(on) {
  document.querySelectorAll('input[data-testid^="approve-"]').forEach((el) => {
    el.disabled = on;
  });
  document.querySelectorAll('[data-testid^="update-"]').forEach((el) => {
    el.disabled = on;
  });
  $("btn-approve-continue").disabled = on;
}

function restoreDraftInputs() {
  const byId = {};
  for (const s of ((S.drafts && S.drafts.sentences) || [])) byId[s.sentence_id] = s;
  document.querySelectorAll('input[data-testid^="approve-"]').forEach((el) => {
    const sid = el.dataset.testid.slice("approve-".length);
    const s = byId[sid];
    el.checked = !!(s && s.approved);
    el.disabled = s ? (s.findings || []).length > 0 : false;
  });
  document.querySelectorAll('[data-testid^="update-"]').forEach((el) => {
    el.disabled = false;
  });
  $("btn-approve-continue").disabled = false;
}

async function refreshSentence(sid) {
  const res = await api("GET", `/api/cases/${S.caseId}/drafts`);
  if (!res.ok) {
    setStatus("초안을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  S.drafts = res.data;
  const s = S.drafts.sentences.find((x) => x.sentence_id === sid);
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  if (s && box) {
    renderFindings(
      box.querySelector(`[data-testid="findings-${sid}"]`), s, S.drafts.gate_results || []);
    const rendered = box.querySelector(`[data-testid="rendered-${sid}"]`);
    rendered.textContent = s.rendered_text;
  }
  renderDraftsGateSummary();
  restoreDraftInputs();
}

function renderDraftsGateSummary() {
  const gates = $("gate-summary");
  gates.innerHTML = "";
  for (const g of (S.drafts.gate_results || [])) {
    if (showGate(g)) gates.appendChild(gateRow(g));
  }
}

async function updateSentence(sid) {
  if (S.putting || S.running) return;
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const text = box.querySelector(`[data-testid="edit-${sid}"]`).value;
  S.putting = true;
  setDraftInputsDisabled(true);
  try {
    const res = await api("PUT", `/api/cases/${S.caseId}/drafts`, {
      sentences: [{ sentence_id: sid, text_with_slots: text }],
    });
    if (!res.ok) {
      setStatus("다시 검사하지 못했습니다. " + errText(res.data));
      return;
    }
    S.drafts = res.data;
    await refreshSentence(sid);
    const s = S.drafts.sentences.find((x) => x.sentence_id === sid);
    const notice = box.querySelector(`[data-testid="notice-${sid}"]`);
    if (s && (s.findings || []).length > 0) {
      notice.textContent = "지적이 있어 승인할 수 없습니다.";
      notice.hidden = false;
    } else if (notice) {
      notice.hidden = true;
    }
  } finally {
    S.putting = false;
    restoreDraftInputs();
  }
}

async function approveSentence(sid) {
  if (S.putting || S.running) {
    const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
    if (box) {
      const cur = (S.drafts.sentences || []).find((x) => x.sentence_id === sid);
      box.querySelector(`[data-testid="approve-${sid}"]`).checked = !!(cur && cur.approved);
    }
    return;
  }
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const want = box.querySelector(`[data-testid="approve-${sid}"]`).checked;
  S.putting = true;
  setDraftInputsDisabled(true);
  try {
    const res = await api("PUT", `/api/cases/${S.caseId}/drafts`, {
      sentences: [{ sentence_id: sid, approved: want }],
    });
    if (!res.ok) {
      setStatus("승인하지 못했습니다. " + errText(res.data));
      return;
    }
    S.drafts = res.data;
    await refreshSentence(sid);
  } finally {
    S.putting = false;
    restoreDraftInputs();
  }
}

async function approveAndContinue() {
  if (S.putting || S.running) return;
  setStatus("");
  S.running = true;
  const gen = ++S.runGen;
  setRunningUI(true);
  $("run-progress").hidden = false;
  try {
    const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
    if (gen !== S.runGen) return;
    if (!res.ok) {
      setStatus("계속하지 못했습니다. " + errText(res.data));
      return;
    }
    S.caseView = res.data;
    renderCaseMeta();
    renderBoard();
    if (S.caseView.state === "CHECKPOINT_2") {
      await loadPackage();
    }
  } finally {
    if (gen === S.runGen) {
      S.running = false;
      setRunningUI(false);
      $("run-progress").hidden = true;
    }
  }
}

/* ---------- package ---------- */

async function loadPackage(opts) {
  const res = await api("GET", `/api/cases/${S.caseId}/package`);
  if (!res.ok) {
    setStatus("서류 묶음을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  S.pkg = res.data;
  const files = $("file-list");
  files.innerHTML = "";
  for (const f of (S.pkg.files || [])) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = f.url;
    a.textContent = f.label;
    a.dataset.testid = `file-${f.name}`;
    li.appendChild(a);
    files.appendChild(li);
  }
  $("claim-purpose").textContent = (S.pkg.ecourt || {}).claim_purpose || "";
  $("claim-cause").textContent = (S.pkg.ecourt || {}).claim_cause_payment_order || "";
  $("pkg-notice").textContent = (S.pkg.notices || {}).notice_ko || "";
  $("pkg-disclaimer").textContent = (S.pkg.notices || {}).disclaimer_ko || "";
  const gates = $("pkg-gates");
  const gateList = $("pkg-gate-list");
  if (gates && gateList) {
    const results = (S.pkg.gate_results || []).filter(showGate);
    gateList.innerHTML = "";
    gates.hidden = results.length === 0;
    for (const g of results) {
      gateList.appendChild(gateRow(g));
    }
  }
  revealSection("package-section", opts && opts.reveal === false ? null : "package-title");
}

async function copyBlock(preId, btn) {
  const text = $(preId).textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch {
      /* ignore */
    }
    ta.remove();
  }
  const orig = btn.textContent;
  btn.textContent = "복사 완료";
  setTimeout(() => { btn.textContent = orig; }, 1200);
}
