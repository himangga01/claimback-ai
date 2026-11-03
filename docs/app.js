/**
 * ClaimBack-AI Frontend Interactive Controller
 * Case display works offline from built-in presets; verification results
 * and packet contents come only from the live FastAPI backend.
 */

let currentJurisdiction = 'KR'; // 'KR' | 'US'
let currentCaseData = null;
let currentVerification = null;

const OFFLINE_MESSAGE = "서버에 연결하면 계산 결과가 표시됩니다.";

// Built-in offline case presets (case data only, no calculations)
const SAMPLE_PRESETS = {
  KR: {
    loan_fact: {
      creditor: { name: "서가온(SAMPLE)", phone: "010-0000-0000", address: "서울특별시 샘플구 데모로 0", city: "서울", state: "서울", zip_code: "00000" },
      debtor: { name: "탁나루(SAMPLE)", phone: "010-0000-0000", address: "경기도 샘플시 데모동 0", city: "샘플시", state: "경기", zip_code: "00000" },
      currency: "KRW",
      transaction_kind: "civil",
      principal_amount: "10000000",
      loan_date: "2026-01-01",
      due_date: "2026-06-30",
      service_date: "2026-08-31",
      evidences: [
        { id: "갑 제1호증", title: "샘플은행 계좌이체확인증", evidence_type: "transfer_receipt", sha256_hash: "8fe6d6d4617185b96cdbbbcac3b9cad0e39f003e4c99977c586a7a4e149d6728", source_filename: "kr_transfer_receipt.txt", extracted_amount: "10000000", extracted_date: "2026-01-01" },
        { id: "갑 제2호증", title: "샘플톡 대화록", evidence_type: "messenger_chat", sha256_hash: "63e31fe59bb5e7c25cd1ff528135e12488318d579c3ec9219e6b4d85dac42e25", source_filename: "kr_chat_log.txt", extracted_date: "2026-06-25" }
      ]
    },
    claim_draft: {
      jurisdiction: "KR",
      claim_amount_claimed: "10000000",
      statement_of_facts: "채무자는 채권자로부터 [갑 제1호증]에 의해 금전을 대여받았고 [갑 제2호증]으로 변제 약정하였으나 불이행함.",
      cited_evidence_ids: ["갑 제1호증", "갑 제2호증"],
      calculation_summary: "원금 10,000,000원 및 지연손해금"
    }
  },
  US: {
    loan_fact: {
      creditor: { name: "Avery Linden (SAMPLE)", phone: "010-0000-0000", address: "0 Sample Street, Sample City", city: "Sample City", state: "CA", zip_code: "00000" },
      debtor: { name: "Rowan Hale (SAMPLE)", phone: "213-555-0144", address: "0 Sample St, Sample City, CA 90000", city: "Sample City", state: "CA", zip_code: "90000" },
      currency: "USD",
      contract_form: "written",
      principal_amount: "5000.00",
      loan_date: "2026-01-10",
      due_date: "2026-04-10",
      evidences: [
        { id: "Exhibit A", title: "Sample Bank Wire Transfer Receipt", evidence_type: "transfer_receipt", sha256_hash: "1bea6080d6dbd79e562e66a81fed0a7efa51081ee9cc8c8c4784cf87f66ea7c4", source_filename: "us_wire_receipt.txt", extracted_amount: "5000.00", extracted_date: "2026-01-10" },
        { id: "Exhibit B", title: "Repayment promise message", evidence_type: "messenger_chat", sha256_hash: "63e31fe59bb5e7c25cd1ff528135e12488318d579c3ec9219e6b4d85dac42e25", source_filename: "sampletalk_chat.png", extracted_date: "2026-04-01" }
      ]
    },
    claim_draft: {
      jurisdiction: "US",
      claim_amount_claimed: "5000.00",
      statement_of_facts: "Defendant received $5,000.00 as personal loan evidenced by [Exhibit A] and promised repayment in [Exhibit B].",
      cited_evidence_ids: ["Exhibit A", "Exhibit B"],
      calculation_summary: "Principal $5,000.00 plus 10% statutory interest"
    }
  }
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  setupEventListeners();
  loadPreset('KR');
});

function setupEventListeners() {
  document.getElementById('btnLoadKR').addEventListener('click', () => {
    switchJurisdiction('KR');
    loadPreset('KR');
  });

  document.getElementById('btnLoadUS').addEventListener('click', () => {
    switchJurisdiction('US');
    loadPreset('US');
  });

  document.getElementById('tabKR').addEventListener('click', () => switchJurisdiction('KR'));
  document.getElementById('tabUS').addEventListener('click', () => switchJurisdiction('US'));

  document.getElementById('btnRunVerify').addEventListener('click', runLiveVerification);

  // Canvas Toggles
  let maskOn = true;
  document.getElementById('toggleMasks').addEventListener('click', () => {
    maskOn = !maskOn;
    document.getElementById('amountBox').style.borderColor = maskOn ? 'rgba(16, 185, 129, 0.8)' : 'rgba(51, 65, 85, 0.4)';
    document.getElementById('chatBox').style.borderColor = maskOn ? 'rgba(59, 130, 246, 0.8)' : 'rgba(51, 65, 85, 0.4)';
  });

  let redactOn = false;
  document.getElementById('toggleRedact').addEventListener('click', () => {
    redactOn = !redactOn;
    const s = document.getElementById('senderRedacted');
    const r = document.getElementById('receiverRedacted');
    if (redactOn) {
      s.classList.add('redacted-blur');
      r.classList.add('redacted-blur');
    } else {
      s.classList.remove('redacted-blur');
      r.classList.remove('redacted-blur');
    }
  });

  let stampOn = true;
  document.getElementById('toggleStamp').addEventListener('click', () => {
    stampOn = !stampOn;
    document.getElementById('stampBadge').style.display = stampOn ? 'block' : 'none';
  });

  // Action Buttons
  document.getElementById('btnDownloadContentProof').addEventListener('click', downloadContentProof);
  document.getElementById('btnDownloadSC100').addEventListener('click', downloadSC100);
  document.getElementById('btnOpenECourtModal').addEventListener('click', openECourtModal);
  document.getElementById('btnCloseModal').addEventListener('click', closeECourtModal);
  document.getElementById('btnCloseModal2').addEventListener('click', closeECourtModal);

  // Copy Buttons inside Modal
  document.querySelectorAll('.btnCopy').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const targetId = e.target.getAttribute('data-target');
      const text = document.getElementById(targetId).innerText;
      navigator.clipboard.writeText(text).then(() => {
        const orig = e.target.innerText;
        e.target.innerText = '복사 완료!';
        e.target.classList.add('text-emerald-300');
        setTimeout(() => {
          e.target.innerText = orig;
          e.target.classList.remove('text-emerald-300');
        }, 1500);
      });
    });
  });
}

function switchJurisdiction(j) {
  currentJurisdiction = j;
  const tabKR = document.getElementById('tabKR');
  const tabUS = document.getElementById('tabUS');
  const krActions = document.getElementById('krActionGroup');
  const usActions = document.getElementById('usActionGroup');

  if (j === 'KR') {
    tabKR.className = "flex-1 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500 text-slate-950 shadow";
    tabUS.className = "flex-1 py-1.5 rounded-lg text-xs font-semibold transition-all text-slate-400 hover:text-slate-200";
    krActions.classList.remove('hidden');
    usActions.classList.add('hidden');
    document.getElementById('stampBadge').innerText = "[갑 제1호증]";
  } else {
    tabUS.className = "flex-1 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500 text-slate-950 shadow";
    tabKR.className = "flex-1 py-1.5 rounded-lg text-xs font-semibold transition-all text-slate-400 hover:text-slate-200";
    usActions.classList.remove('hidden');
    krActions.classList.add('hidden');
    document.getElementById('stampBadge').innerText = "[Exhibit A]";
  }
}

function loadPreset(j) {
  currentCaseData = SAMPLE_PRESETS[j];
  renderCaseData(currentCaseData);
  runLiveVerification();
}

function renderCaseData(data) {
  const lf = data.loan_fact;
  document.getElementById('metaCreditor').innerText = lf.creditor.name;
  document.getElementById('metaDebtor').innerText = lf.debtor.name;
  document.getElementById('metaPrincipal').innerText = lf.currency === 'KRW' ? `${Number(lf.principal_amount).toLocaleString()}원` : `$${Number(lf.principal_amount).toLocaleString()} USD`;
  document.getElementById('metaDueDate').innerText = lf.due_date;

  // Render Evidence List
  const list = document.getElementById('evidenceList');
  list.innerHTML = '';
  document.getElementById('evidenceCount').innerText = `${lf.evidences.length}건`;

  lf.evidences.forEach((ev, idx) => {
    const card = document.createElement('div');
    card.className = "p-3 rounded-xl border border-slate-800 bg-slate-900/50 hover:border-slate-700 transition-all flex flex-col gap-1.5";
    card.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="font-bold text-xs text-slate-200">${ev.id} · ${ev.title}</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/80 font-mono">Verified</span>
      </div>
      <div class="flex items-center justify-between text-[11px] text-slate-400">
        <span>파일: <span class="font-mono text-slate-300">${ev.source_filename}</span></span>
        <span>${ev.extracted_amount ? `${Number(ev.extracted_amount).toLocaleString()}` : ''}</span>
      </div>
      <div class="flex items-center gap-1 font-mono text-[10px] text-slate-500 truncate">
        <span>SHA256:</span>
        <span class="text-slate-400 truncate">${ev.sha256_hash}</span>
      </div>
    `;
    list.appendChild(card);
  });

  // Canvas details
  document.getElementById('canvasAmount').innerText = lf.currency === 'KRW' ? `${Number(lf.principal_amount).toLocaleString()} KRW` : `$${Number(lf.principal_amount).toLocaleString()} USD`;
  document.getElementById('canvasHash').innerText = lf.evidences[0]?.sha256_hash.substring(0, 16) + '...';
  document.getElementById('timeLoanDate').innerText = lf.loan_date;
  document.getElementById('timeDueDate').innerText = lf.due_date;
  document.getElementById('timeServiceDate').innerText = lf.service_date || '송달 전 (연 5% 적용)';

  if (window.lucide) window.lucide.createIcons();
}

async function runLiveVerification() {
  const auditBox = document.getElementById('auditLogBox');
  auditBox.innerHTML = '<div class="text-emerald-400 animate-pulse">Running Deterministic Verification Gate...</div>';

  try {
    const res = await fetch('/api/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        loan_fact: currentCaseData.loan_fact,
        claim_draft: currentCaseData.claim_draft,
        target_date: '2026-10-31'
      })
    });

    if (res.ok) {
      currentVerification = await res.json();
      updateVerificationUI(currentVerification);
    } else {
      throw new Error(`API status ${res.status}`);
    }
  } catch (err) {
    // No offline calculation: without the server there is nothing to show.
    console.warn("Backend API not reachable:", err);
    showOfflineNotice();
  }
}

function updateVerificationUI(ver) {
  const badge = document.getElementById('gateBadge');
  const card = document.getElementById('gateCard');
  const msg = document.getElementById('gateMessage');
  const auditBox = document.getElementById('auditLogBox');

  badge.innerText = ver.status;

  if (ver.status === 'PASS') {
    badge.className = "text-xs font-extrabold px-2.5 py-0.5 rounded-full bg-emerald-500 text-slate-950 tracking-wider";
    card.className = "rounded-xl border border-emerald-500/40 bg-emerald-950/20 p-4 transition-all";
    msg.className = "mt-3 p-2.5 rounded-lg bg-emerald-900/30 border border-emerald-800/50 text-[11px] text-emerald-200 leading-relaxed";
    msg.innerText = "서버 검증 결과: " + ver.status;
  } else if (ver.status === 'RECONCILED') {
    badge.className = "text-xs font-extrabold px-2.5 py-0.5 rounded-full bg-amber-500 text-slate-950 tracking-wider";
    card.className = "rounded-xl border border-amber-500/40 bg-amber-950/20 p-4 transition-all";
    msg.className = "mt-3 p-2.5 rounded-lg bg-amber-900/30 border border-amber-800/50 text-[11px] text-amber-200 leading-relaxed";
    msg.innerText = ver.tampering_reconciliations.join('\n');
  } else {
    badge.className = "text-xs font-extrabold px-2.5 py-0.5 rounded-full bg-rose-500 text-white tracking-wider";
    card.className = "rounded-xl border border-rose-500/40 bg-rose-950/20 p-4 transition-all";
    msg.className = "mt-3 p-2.5 rounded-lg bg-rose-900/30 border border-rose-800/50 text-[11px] text-rose-200 leading-relaxed";
    msg.innerText = ver.missing_requirements.join('\n');
  }

  const cur = currentCaseData.loan_fact.currency;
  const p = Number(ver.reconciled_amount);
  const i = Number(ver.calculated_interest);
  const t = Number(ver.total_claim_amount);

  document.getElementById('cardPrincipal').innerText = cur === 'KRW' ? `${p.toLocaleString()}원` : `$${p.toFixed(2)} USD`;
  document.getElementById('cardInterest').innerText = cur === 'KRW' ? `${i.toLocaleString()}원` : `$${i.toFixed(2)} USD`;
  document.getElementById('cardTotal').innerText = cur === 'KRW' ? `${t.toLocaleString()}원` : `$${t.toFixed(2)} USD`;

  auditBox.innerHTML = '';
  ver.audit_notes.forEach(note => {
    const div = document.createElement('div');
    div.className = note.includes('통과') || note.includes('발생') ? 'text-emerald-400' : 'text-slate-300';
    div.innerText = `[LOG] ${note}`;
    auditBox.appendChild(div);
  });
}

function showOfflineNotice() {
  currentVerification = null;
  const badge = document.getElementById('gateBadge');
  const card = document.getElementById('gateCard');
  const msg = document.getElementById('gateMessage');
  const auditBox = document.getElementById('auditLogBox');

  badge.innerText = "OFFLINE";
  badge.className = "text-xs font-extrabold px-2.5 py-0.5 rounded-full bg-slate-500 text-white tracking-wider";
  card.className = "rounded-xl border border-slate-700 bg-slate-900/40 p-4 transition-all";
  msg.className = "mt-3 p-2.5 rounded-lg bg-slate-900/60 border border-slate-700 text-[11px] text-slate-300 leading-relaxed";
  msg.innerText = OFFLINE_MESSAGE;

  document.getElementById('cardPrincipal').innerText = "–";
  document.getElementById('cardInterest').innerText = "–";
  document.getElementById('cardTotal').innerText = "–";

  auditBox.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'text-slate-400';
  div.innerText = OFFLINE_MESSAGE;
  auditBox.appendChild(div);
}

async function downloadSC100() {
  try {
    const res = await fetch('/api/compile/sc100', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        loan_fact: currentCaseData.loan_fact,
        claim_draft: currentCaseData.claim_draft,
        target_date: '2026-10-31'
      })
    });
    if (!res.ok) throw new Error("Compilation failed");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `SC-100_${currentCaseData.loan_fact.debtor.name.replace(/\s+/g, '_')}.pdf`;
    a.click();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    alert("백엔드 서버(/api/compile/sc100)를 연결하여 PDF 다운로드를 실행하세요.");
  }
}

async function downloadContentProof() {
  try {
    const res = await fetch('/api/compile/content-proof', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        loan_fact: currentCaseData.loan_fact,
        claim_draft: currentCaseData.claim_draft,
        target_date: '2026-10-31'
      })
    });
    if (!res.ok) throw new Error("Compilation failed");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `내용증명_${currentCaseData.loan_fact.debtor.name}.pdf`;
    a.click();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    alert("백엔드 서버(/api/compile/content-proof)를 연결하여 PDF 다운로드를 실행하세요.");
  }
}

async function openECourtModal() {
  const modal = document.getElementById('ecourtModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');

  try {
    const res = await fetch('/api/compile/ecourt-packet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        loan_fact: currentCaseData.loan_fact,
        claim_draft: currentCaseData.claim_draft,
        target_date: '2026-10-31'
      })
    });
    if (res.ok) {
      const packet = await res.json();
      document.getElementById('copyParties').innerText = packet.parties;
      document.getElementById('copyPurpose').innerText = packet.claim_purpose;
      document.getElementById('copyCause').innerText = packet.claim_cause_payment_order;
      return;
    }
  } catch (err) {
    console.warn("Backend API not reachable for ecourt packet:", err);
  }

  // No offline fallback text: packet contents come from the server.
  const lf = currentCaseData.loan_fact;
  document.getElementById('copyParties').innerText = `채권자: ${lf.creditor.name} (${lf.creditor.address})\n채무자: ${lf.debtor.name} (${lf.debtor.address})`;
  document.getElementById('copyPurpose').innerText = OFFLINE_MESSAGE;
  document.getElementById('copyCause').innerText = OFFLINE_MESSAGE;
}

function closeECourtModal() {
  const modal = document.getElementById('ecourtModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}
