/* ClaimBack-AI case-flow screen (M2b). Vanilla JS, no build, no external scripts. */
"use strict";

const S = {
  caseId: null,
  caseView: null,
  readings: [],
  review: null,
  drafts: null,
  pkg: null,
  selectedEx: null,
  pollTimer: null,
  serverOk: false,
};

const AGENTS = [
  { group: "Forensic Visual", desc: "증거 접수와 목록 정리" },
  { group: "Fact-Timeline Chronology", desc: "증거 읽기와 사실 정리" },
  { group: "Financial Auditor", desc: "계산과 숫자 대조" },
  { group: "Judicial Form Filler", desc: "서류 묶음 만들기" },
  { group: "User", desc: "사람이 값과 문장을 확인" },
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
  reminder: "독촉",
  other: "기타",
};

const ROLE_OPTIONS = [
  ["loan_transfer", "대여 이체"],
  ["repayment", "변제 입금"],
  ["loan_agreement", "차용증"],
  ["chat", "대화 기록"],
  ["other", "기타"],
];

function $(id) {
  return document.getElementById(id);
}

function setStatus(msg) {
  $("status-line").textContent = msg || "";
}

function errText(data) {
  if (data && data.detail) {
    if (typeof data.detail === "string") return data.detail;
    if (data.detail.message) return data.detail.message;
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

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- boot ---------- */

document.addEventListener("DOMContentLoaded", () => {
  $("btn-sample").addEventListener("click", loadSample);
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

/* ---------- case lifecycle ---------- */

async function loadSample() {
  setStatus("");
  const res = await api("POST", "/api/cases/sample", { set: "kr" });
  if (!res.ok) {
    setStatus("사건을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  S.caseId = res.data.case_id;
  S.caseView = res.data;
  S.readings = [];
  S.review = null;
  S.drafts = null;
  S.pkg = null;
  S.selectedEx = null;
  renderCaseMeta();
  renderBoard();
  $("btn-delete").disabled = false;
  await runWithPolling();
  if (S.caseView && S.caseView.state === "CHECKPOINT_1") {
    await loadCheckpoint1();
  }
}

async function runWithPolling() {
  $("run-progress").hidden = false;
  const poll = async () => {
    const res = await api("GET", `/api/cases/${S.caseId}`);
    if (res.ok) {
      S.caseView = res.data;
      renderCaseMeta();
      renderBoard();
    }
  };
  S.pollTimer = setInterval(poll, 500);
  try {
    const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
    if (!res.ok) {
      setStatus("실행하지 못했습니다. " + errText(res.data));
    } else {
      S.caseView = res.data;
    }
  } finally {
    clearInterval(S.pollTimer);
    S.pollTimer = null;
    $("run-progress").hidden = true;
  }
  const cur = await api("GET", `/api/cases/${S.caseId}`);
  if (cur.ok) S.caseView = cur.data;
  renderCaseMeta();
  renderBoard();
}

async function deleteCase() {
  if (!S.caseId) return;
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
  $("btn-delete").disabled = true;
  for (const id of ["board-section", "checkpoint-section", "calc-section",
    "drafts-section", "package-section"]) {
    $(id).hidden = true;
  }
  document.querySelector(".case-meta").hidden = true;
  $("stub-banner").hidden = true;
  $("replay-badge").hidden = true;
  setStatus("사건을 삭제했습니다.");
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
    S.caseId = created.data.case_id;
    S.caseView = created.data;
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
  $("case-state").textContent = v.state;
  $("stub-banner").hidden = !v.stub;
  $("replay-badge").hidden = v.meta_mode !== "replay";
  $("board-section").hidden = false;
}

function renderBoard() {
  const v = S.caseView;
  if (!v) return;
  renderHold(v);
  const board = $("agent-board");
  board.innerHTML = "";
  for (const a of AGENTS) {
    const steps = v.steps.filter((s) => s.group === a.group);
    if (steps.length === 0) continue;
    const card = document.createElement("div");
    card.className = "agent-card";
    card.dataset.testid = `agent-card-${a.group}`;
    const h = document.createElement("h3");
    h.textContent = a.group === "User" ? "사용자 확인" : a.group;
    card.appendChild(h);
    const d = document.createElement("p");
    d.className = "agent-desc";
    d.textContent = a.desc;
    card.appendChild(d);
    for (const s of steps) {
      const row = document.createElement("div");
      row.className = "step-row" + (s.status === "skipped" ? " is-skipped" : "");
      row.dataset.testid = `step-${s.key}`;
      const head = document.createElement("div");
      head.className = "step-head";
      const agent = document.createElement("span");
      agent.className = "step-agent";
      agent.textContent = s.agent;
      head.appendChild(agent);
      const model = document.createElement("span");
      model.className = "model-badge";
      model.textContent = s.model || (s.group === "User" ? "—" : "규칙");
      head.appendChild(model);
      const st = document.createElement("span");
      st.className = "step-status";
      st.dataset.status = s.status;
      st.textContent = STATUS_KO[s.status] || s.status;
      head.appendChild(st);
      const meta = document.createElement("span");
      meta.className = "step-meta";
      meta.textContent = `${fmtLatency(s.latency_ms || 0)} · $${s.cost_usd || "0"}`;
      head.appendChild(meta);
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
          li.textContent = `${exLabel(sub.ex_id)} · ${STATUS_KO[sub.status] || sub.status} · ${fmtLatency(sub.latency_ms || 0)}`;
          ul.appendChild(li);
        }
        row.appendChild(ul);
      }
      card.appendChild(row);
    }
    board.appendChild(card);
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
    label.appendChild(check);
    const msg = document.createElement("span");
    msg.textContent = " " + (r.code === "replay_fixture_missing"
      ? "기록된 응답이 없는 입력입니다"
      : (r.message || r.code || ""));
    label.appendChild(msg);
    li.appendChild(label);
    list.appendChild(li);
  });
}

/* ---------- checkpoint 1 ---------- */

async function loadCheckpoint1() {
  const [rd, rv] = await Promise.all([
    api("GET", `/api/cases/${S.caseId}/readings`),
    api("GET", `/api/cases/${S.caseId}/review`),
  ]);
  if (!rd.ok || !rv.ok) {
    setStatus("사실 확인 자료를 불러오지 못했습니다.");
    return;
  }
  S.readings = rd.data;
  S.review = rv.data;
  renderCheckpoint();
  $("checkpoint-section").hidden = false;
}

function readingsFor(exId) {
  const r = S.readings.find((x) => x.ex_id === exId);
  return r ? r.items : [];
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
    const evStatus = { ok: "정상", hold: "보류", skipped: "건너뜀" }[e.status] || e.status;
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
    return;
  }
  empty.hidden = true;
  img.hidden = false;
  img.src = e.preview_url;
  if (items.length === 0) {
    $("reading-note").textContent = "판독 결과 없음";
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
}

function blinkBox(exId, itemId) {
  selectEvidence(exId);
  requestAnimationFrame(() => {
    const el = document.querySelector(`[data-testid="reading-box-${exId}-${itemId}"]`);
    if (el) {
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
  });
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
      f.value.forEach((r, i) => {
        const wrap = document.createElement("div");
        const d = document.createElement("input");
        d.type = "date";
        d.value = r.date || "";
        d.dataset.testid = `field-repayments-${i}-date`;
        const a = document.createElement("input");
        a.type = "text";
        a.value = r.amount || "";
        a.dataset.testid = `field-repayments-${i}-amount`;
        wrap.appendChild(d);
        wrap.appendChild(a);
        tdVal.appendChild(wrap);
      });
      if (f.value.length === 0) {
        const span = document.createElement("span");
        span.textContent = f.display || "없음";
        tdVal.appendChild(span);
      }
    } else if (f.field === "transaction_kind") {
      const sel = document.createElement("select");
      sel.dataset.testid = "field-transaction_kind";
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
      input.placeholder = f.display || "";
      input.dataset.testid = `field-${f.field}`;
      tdVal.appendChild(input);
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

function renderConflicts() {
  const ul = $("conflict-list");
  ul.innerHTML = "";
  const items = [];
  for (const c of (S.review.conflicts || [])) items.push(typeof c === "string" ? c : JSON.stringify(c));
  for (const q of (S.review.questions || [])) items.push(q.question || `${q.field} 입력 필요`);
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

function renderUtterances() {
  const ul = $("utterance-list");
  ul.innerHTML = "";
  for (const u of (S.review.utterances || [])) {
    const li = document.createElement("li");
    li.dataset.testid = `utterance-${u.ex_id}-${u.item_id}`;
    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.testid = `highlight-${u.ex_id}-${u.item_id}`;
    label.appendChild(check);
    const em = document.createElement("span");
    em.textContent = " 강조 ";
    label.appendChild(em);
    li.appendChild(label);
    const body = document.createElement("span");
    body.textContent = `${u.speaker}: ${u.text} `;
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
    for (const [val, name] of ROLE_OPTIONS) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = name;
      if (r.suggested_role === val) opt.selected = true;
      sel.appendChild(opt);
    }
    label.appendChild(sel);
    li.appendChild(label);
    ul.appendChild(li);
  }
}

function gatherFacts() {
  const fields = {};
  for (const f of S.review.fields) {
    if (f.field === "repayments" && Array.isArray(f.value)) {
      fields.repayments = f.value.map((_, i) => ({
        date: document.querySelector(`[data-testid="field-repayments-${i}-date"]`).value,
        amount: document.querySelector(`[data-testid="field-repayments-${i}-amount"]`).value,
      }));
    } else if (f.field === "transaction_kind") {
      fields[f.field] = document.querySelector('[data-testid="field-transaction_kind"]').value;
    } else {
      const el = document.querySelector(`[data-testid="field-${f.field}"]`);
      const val = el.value.trim();
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

async function confirmFacts() {
  setStatus("");
  const body = gatherFacts();
  const put = await api("PUT", `/api/cases/${S.caseId}/facts`, body);
  if (!put.ok) {
    setStatus("확정값을 저장하지 못했습니다. " + errText(put.data));
    return;
  }
  S.caseView = put.data;
  renderCaseMeta();
  renderBoard();
  await runWithPolling();
  if (S.caseView && S.caseView.state === "DRAFT_APPROVAL") {
    await loadDrafts();
  }
}

/* ---------- calculation + draft approval ---------- */

async function loadDrafts() {
  const res = await api("GET", `/api/cases/${S.caseId}/drafts`);
  if (!res.ok) {
    setStatus("초안을 불러오지 못했습니다. " + errText(res.data));
    return;
  }
  S.drafts = res.data;
  renderCalc();
  renderDrafts();
  $("calc-section").hidden = false;
  $("drafts-section").hidden = false;
}

function fmtWon(amountStr) {
  const n = Number(String(amountStr).split(".")[0]);
  if (!Number.isFinite(n)) return String(amountStr);
  return n.toLocaleString("ko-KR") + "원";
}

function renderCalc() {
  const calc = S.drafts.calculation;
  $("calc-title").textContent =
    `입력한 사실 기준 계산(기준일 ${fmtDateDots(calc.reference_total.as_of)})`;
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
    rev.textContent = `문안 작성 ⇄ 검증 ${d.revision_rounds}회`;
  } else {
    rev.hidden = true;
  }
  const gates = $("gate-summary");
  gates.innerHTML = "";
  for (const g of (d.gate_results || [])) {
    const row = document.createElement("div");
    row.className = "gate-row";
    row.dataset.testid = `gate-${g.gate}`;
    row.textContent = `${g.gate}: ${g.status === "pass" ? "통과" : g.status === "fail" ? "지적 있음" : g.status}`;
    gates.appendChild(row);
  }
  const list = $("sentence-list");
  list.innerHTML = "";
  for (const s of (d.sentences || [])) {
    list.appendChild(sentenceEl(s, d.gate_results || []));
  }
}

function sentenceEl(s, gateResults) {
  const box = document.createElement("div");
  box.className = "sentence";
  box.dataset.testid = `sentence-${s.sentence_id}`;

  const head = document.createElement("div");
  head.className = "sentence-head";
  const id = document.createElement("span");
  id.className = "sentence-id";
  id.textContent = `문장 ${s.sentence_id}`;
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

  const edit = document.createElement("textarea");
  edit.dataset.testid = `edit-${s.sentence_id}`;
  edit.value = s.text_with_slots;
  box.appendChild(edit);

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
    return;
  }
  const byGate = {};
  for (const g of gateResults) {
    for (const f of (g.findings || [])) {
      if (f.sentence_id === s.sentence_id) {
        (byGate[g.gate] = byGate[g.gate] || []).push(f);
      }
    }
  }
  const gates = Object.keys(byGate);
  const groups = gates.length > 0 ? gates : ["G1a"];
  for (const gate of groups) {
    const line = document.createElement("div");
    const name = document.createElement("span");
    name.className = "gate-name";
    name.textContent = `${gate}: `;
    line.appendChild(name);
    const items = byGate[gate] || mine;
    line.appendChild(document.createTextNode(
      items.map((f) => `${f.message} (${f.fix_hint})`).join(" / ")));
    el.appendChild(line);
  }
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
    const approve = box.querySelector(`[data-testid="approve-${sid}"]`);
    approve.checked = !!s.approved;
    approve.disabled = (s.findings || []).length > 0;
    const rendered = box.querySelector(`[data-testid="rendered-${sid}"]`);
    rendered.textContent = s.rendered_text;
  }
  renderDraftsGateSummary();
}

function renderDraftsGateSummary() {
  const gates = $("gate-summary");
  gates.innerHTML = "";
  for (const g of (S.drafts.gate_results || [])) {
    const row = document.createElement("div");
    row.className = "gate-row";
    row.dataset.testid = `gate-${g.gate}`;
    row.textContent = `${g.gate}: ${g.status === "pass" ? "통과" : g.status === "fail" ? "지적 있음" : g.status}`;
    gates.appendChild(row);
  }
}

async function updateSentence(sid) {
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const text = box.querySelector(`[data-testid="edit-${sid}"]`).value;
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
  if (s && (s.findings || []).length > 0) {
    setStatus("지적이 있어 승인할 수 없습니다.");
  }
}

async function approveSentence(sid) {
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const want = box.querySelector(`[data-testid="approve-${sid}"]`).checked;
  const res = await api("PUT", `/api/cases/${S.caseId}/drafts`, {
    sentences: [{ sentence_id: sid, approved: want }],
  });
  if (!res.ok) {
    setStatus("승인하지 못했습니다. " + errText(res.data));
    return;
  }
  S.drafts = res.data;
  await refreshSentence(sid);
}

async function approveAndContinue() {
  setStatus("");
  const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
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
}

/* ---------- package ---------- */

async function loadPackage() {
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
  $("package-section").hidden = false;
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
