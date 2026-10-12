/**
 * PaperPulse - GenAI-Powered Requirements-to-Test Automation
 * Frontend Client Application Logic
 */

const API_BASE = window.location.origin;
let authToken = localStorage.getItem("paperpulse_token") || null;
let currentDocumentId = null;
let currentRequirements = [];
let currentTestCases = [];

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initUpload();
  await ensureAuthentication();
  await loadDocumentsList();
});

// Toast Notifications
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Loading Spinner
function setSpinner(active, message = "Processing with Google Gemini...") {
  const spinner = document.getElementById("spinner-overlay");
  const msgEl = document.getElementById("spinner-text");
  if (msgEl) msgEl.innerText = message;
  if (spinner) {
    if (active) spinner.classList.add("active");
    else spinner.classList.remove("active");
  }
}

// Authentication
async function ensureAuthentication() {
  if (authToken) {
    try {
      const res = await fetch(`${API_BASE}/users/me`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (res.ok) {
        const user = await res.json();
        updateAuthBadge(user.email);
        return;
      }
    } catch (e) {
      console.warn("Existing token invalid or expired.");
    }
  }

  // Auto-login or register demo user
  const email = "sdlc_engineer@paperpulse.ai";
  const password = "Password123!";

  try {
    const regRes = await fetch(`${API_BASE}/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch (e) {
    // User may already exist
  }

  try {
    const formData = new URLSearchParams();
    formData.append("username", email);
    formData.append("password", password);

    const loginRes = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: formData,
    });

    if (loginRes.ok) {
      const data = await loginRes.json();
      authToken = data.access_token;
      localStorage.setItem("paperpulse_token", authToken);
      updateAuthBadge(email);
    }
  } catch (err) {
    showToast("Authentication setup error: " + err.message, "error");
  }
}

function updateAuthBadge(email) {
  const el = document.getElementById("auth-badge");
  if (el) el.innerHTML = `👤 <strong>${email}</strong>`;
}

// Tab Switching
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add("active");

      // Auto refresh coverage on dashboard tab
      if (targetId === "tab-dashboard" && currentDocumentId) {
        refreshDashboardMetrics();
      }
    });
  });
}

// Document Upload & Drag-and-Drop
function initUpload() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  if (!dropzone || !fileInput) return;

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) {
      handleFileUpload(e.target.files[0]);
    }
  });

  // Sample document quick loader
  const sampleBtn = document.getElementById("btn-load-sample");
  if (sampleBtn) {
    sampleBtn.addEventListener("click", loadSampleRequirementsDocument);
  }
}

async function handleFileUpload(file) {
  if (!authToken) {
    showToast("Please wait for authentication to complete.", "error");
    return;
  }

  setSpinner(true, `Ingesting '${file.name}' using PyMuPDF & OCR...`);
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to upload document");
    }

    const doc = await res.json();
    currentDocumentId = doc.id;
    showToast(`Successfully uploaded '${doc.filename}' (${doc.pages_total} pages processed).`, "success");
    await loadDocumentsList();
    await extractRequirementsForDoc(doc.id);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setSpinner(false);
  }
}

// Quick Sample Requirements Loader for Demo / Judging
async function loadSampleRequirementsDocument() {
  setSpinner(true, "Loading synthetic enterprise software requirements document...");

  const sampleSRS = `SOFTWARE REQUIREMENTS SPECIFICATION (SRS)
Project: PulseCommerce Cloud Checkout & Payment Platform
Version: 2.4.0
Status: Approved for Engineering

1. FEATURE: SECURE USER AUTHENTICATION & SESSION MANAGEMENT
REQ-001: The platform shall authenticate registered customers via email address and password. Passwords must be at least 8 characters in length containing an uppercase letter, a number, and a symbol. Upon 5 consecutive failed login attempts, the account must be temporarily locked for 15 minutes. Successful login returns an encrypted JWT session token.
Preconditions: Customer account exists in registered state.
Acceptance Criteria:
- AC-01: Valid credentials return HTTP 200 with JWT access token.
- AC-02: Invalid password returns HTTP 401 with generic error message.
- AC-03: 5 consecutive failures triggers temporary account lockout with HTTP 423 Locked.

2. FEATURE: BASKET VALIDATION AND PROMOTION ENGINE
REQ-002: The checkout service shall validate basket contents and enforce promotional coupon discount rules. Discount codes must not reduce the total payable amount below $0.00. Expired or malformed coupons must be rejected with explicit error codes.
Preconditions: Customer has an active checkout session with >= 1 line item.
Acceptance Criteria:
- AC-01: Valid coupon code deducts exact percentage discount from eligible items.
- AC-02: Total amount payable cannot be less than zero.
- AC-03: Expired coupon returns HTTP 400 with 'COUPON_EXPIRED'.

3. FEATURE: PAYMENT GATEWAY INTEGRATION & IDEMPOTENCY
REQ-003: The system shall process credit card transactions via external payment provider API. Every checkout payment request must include an 'Idempotency-Key' header. If an identical idempotency key is submitted within 24 hours, the system must return the original transaction receipt without double-charging the customer.
Preconditions: Order total is calculated and payment method token is validated.
Acceptance Criteria:
- AC-01: Valid charge returns HTTP 200 and generates unique transaction ID.
- AC-02: Duplicate submission with identical idempotency key returns HTTP 200 original receipt with 0 duplicate charges.

4. FEATURE: TRANSACTION LATENCY & THROUGHPUT CONSTRAINTS
REQ-004: Payment authorization latency must not exceed 2.5 seconds at the 99th percentile under concurrent loads up to 1,000 requests per second.
Category: Performance
Acceptance Criteria:
- AC-01: P99 latency <= 2500ms under standard peak simulation.`;

  const blob = new Blob([sampleSRS], { type: "text/plain" });
  const sampleFile = new File([blob], "PulseCommerce_Checkout_SRS.txt", { type: "text/plain" });

  await handleFileUpload(sampleFile);
}

// Load List of Documents
async function loadDocumentsList() {
  if (!authToken) return;

  try {
    const res = await fetch(`${API_BASE}/sdlc/documents`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (res.ok) {
      const docs = await res.json();
      renderDocumentsTable(docs);
      if (docs.length > 0 && !currentDocumentId) {
        currentDocumentId = docs[0].id;
        await loadRequirementsForDoc(currentDocumentId);
      }
    }
  } catch (err) {
    console.error("Error loading documents:", err);
  }
}

function renderDocumentsTable(docs) {
  const tbody = document.getElementById("documents-tbody");
  if (!tbody) return;

  if (docs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:2rem;">No documents uploaded yet. Drag & drop a PDF above or click 'Load Demo Requirements'.</td></tr>`;
    return;
  }

  tbody.innerHTML = docs
    .map(
      (d) => `
    <tr class="${d.id === currentDocumentId ? 'selected-row' : ''}">
      <td><strong>#${d.id}</strong></td>
      <td><strong>${d.filename}</strong></td>
      <td>${d.pages_total} pages (${d.pages_ocr} OCR)</td>
      <td>${d.character_count.toLocaleString()} chars</td>
      <td><span class="badge ${d.status === 'tests_generated' ? 'badge-approved' : 'badge-pending'}">${d.status}</span></td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="selectDocument(${d.id})">Select</button>
        <button class="btn btn-primary btn-sm" onclick="extractRequirementsForDoc(${d.id})">Extract REQs</button>
      </td>
    </tr>
  `
    )
    .join("");
}

async function selectDocument(docId) {
  currentDocumentId = docId;
  showToast(`Selected document #${docId}`, "info");
  await loadDocumentsList();
  await loadRequirementsForDoc(docId);
  await loadTestCasesForDoc(docId);
  await refreshDashboardMetrics();
}

// Extract Requirements
async function extractRequirementsForDoc(docId) {
  currentDocumentId = docId;
  setSpinner(true, "Google Gemini analyzing requirements document & extracting structured records...");

  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/${docId}/extract-requirements`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (!res.ok) throw new Error("Requirements extraction failed");

    const reqs = await res.json();
    currentRequirements = reqs;
    showToast(`Extracted ${reqs.length} requirements with Pydantic validation!`, "success");
    renderRequirementsTable(reqs);

    // Switch to Requirements tab
    document.querySelector('[data-tab="tab-requirements"]').click();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setSpinner(false);
  }
}

// Load Requirements
async function loadRequirementsForDoc(docId) {
  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/${docId}/requirements`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      currentRequirements = await res.json();
      renderRequirementsTable(currentRequirements);
    }
  } catch (e) {
    console.error(e);
  }
}

function renderRequirementsTable(reqs) {
  const tbody = document.getElementById("requirements-tbody");
  if (!tbody) return;

  if (reqs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:2rem;">No requirements extracted yet. Click 'Extract REQs' on an uploaded document.</td></tr>`;
    return;
  }

  tbody.innerHTML = reqs
    .map((r, idx) => {
      const statusBadge =
        r.review_status === "Approved"
          ? "badge-approved"
          : r.review_status === "Rejected"
          ? "badge-rejected"
          : r.review_status === "Needs Revision"
          ? "badge-revision"
          : "badge-pending";

      const catBadge =
        r.category === "security"
          ? "badge-security"
          : r.category === "performance"
          ? "badge-performance"
          : r.category === "business_rule"
          ? "badge-business"
          : "badge-functional";

      const ambiguitiesHtml =
        r.ambiguities && r.ambiguities.length > 0
          ? `<div style="font-size:0.75rem; color:#f87171; margin-top:0.35rem;">⚠️ <strong>Ambiguity Flag:</strong> ${r.ambiguities[0]}</div>`
          : "";

      return `
      <tr>
        <td><strong>${r.id}</strong></td>
        <td><span class="badge ${catBadge}">${r.category}</span></td>
        <td>
          <div style="font-weight:700; color:var(--text-primary);">${r.title}</div>
          <div style="font-size:0.8rem; color:var(--text-secondary); margin-top:0.2rem;">${r.description}</div>
          ${ambiguitiesHtml}
        </td>
        <td>${r.acceptance_criteria ? r.acceptance_criteria.length : 0} criteria</td>
        <td><span class="badge ${statusBadge}">${r.review_status}</span></td>
        <td>
          <div style="display:flex; gap:0.35rem; flex-wrap:wrap;">
            <button class="btn btn-success btn-sm" onclick="setRequirementStatus(${idx + 1}, 'Approved')">Approve</button>
            <button class="btn btn-danger btn-sm" onclick="setRequirementStatus(${idx + 1}, 'Rejected')">Reject</button>
            <button class="btn btn-secondary btn-sm" onclick="openRequirementModal(${idx})">Edit</button>
            <button class="btn btn-primary btn-sm" onclick="generateTestsForReq(${idx + 1})">Gen Tests</button>
          </div>
        </td>
      </tr>
    `;
    })
    .join("");
}

async function setRequirementStatus(dbId, status) {
  try {
    const res = await fetch(`${API_BASE}/sdlc/requirements/${dbId}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ review_status: status }),
    });

    if (res.ok) {
      showToast(`Requirement status updated to ${status}.`, "success");
      await loadRequirementsForDoc(currentDocumentId);
      await refreshDashboardMetrics();
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Generate Tests for All Requirements
async function generateAllTests() {
  if (!currentDocumentId) {
    showToast("Please upload or select a document first.", "error");
    return;
  }

  setSpinner(true, "Generating Positive, Negative, Boundary, Edge Case & Integration Test Cases via Gemini...");

  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/${currentDocumentId}/generate-all-tests?only_approved=false`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Test generation failed");
    }

    const data = await res.json();
    showToast(`Generated ${data.test_suite.total_test_cases} test cases successfully!`, "success");
    await loadTestCasesForDoc(currentDocumentId);
    await refreshDashboardMetrics();

    // Switch to test cases tab
    document.querySelector('[data-tab="tab-testcases"]').click();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setSpinner(false);
  }
}

// Generate Tests for Single Requirement
async function generateTestsForReq(dbId) {
  setSpinner(true, "Generating test scenarios across all 5 test categories...");

  try {
    const res = await fetch(`${API_BASE}/sdlc/requirements/${dbId}/generate-tests`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (!res.ok) throw new Error("Single requirement test generation failed");

    const data = await res.json();
    showToast(`Generated ${data.test_cases.length} test cases!`, "success");
    await loadTestCasesForDoc(currentDocumentId);
    await refreshDashboardMetrics();
    document.querySelector('[data-tab="tab-testcases"]').click();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    setSpinner(false);
  }
}

// Load Test Cases
async function loadTestCasesForDoc(docId) {
  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/${docId}/test-cases`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      currentTestCases = await res.json();
      renderTestCasesTable(currentTestCases);
    }
  } catch (e) {
    console.error(e);
  }
}

function renderTestCasesTable(cases) {
  const tbody = document.getElementById("testcases-tbody");
  if (!tbody) return;

  if (cases.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:2rem;">No test cases generated yet. Click 'Generate Complete Test Suite' above.</td></tr>`;
    return;
  }

  tbody.innerHTML = cases
    .map((tc, idx) => {
      const catBadge =
        tc.category === "positive"
          ? "badge-positive"
          : tc.category === "negative"
          ? "badge-negative"
          : tc.category === "boundary"
          ? "badge-boundary"
          : tc.category === "edge_case"
          ? "badge-edge"
          : "badge-integration";

      const priBadge =
        tc.priority === "Critical"
          ? "badge-critical"
          : tc.priority === "High"
          ? "badge-high"
          : tc.priority === "Medium"
          ? "badge-medium"
          : "badge-low";

      const statusBadge =
        tc.review_status === "Approved"
          ? "badge-approved"
          : tc.review_status === "Rejected"
          ? "badge-rejected"
          : "badge-pending";

      const stepsPreview = tc.steps && tc.steps.length ? tc.steps.slice(0, 2).join("<br>") : "No steps defined";

      return `
      <tr>
        <td><strong>${tc.id}</strong></td>
        <td><span class="badge" style="background:#1e293b; color:#38bdf8;">${tc.requirement_id}</span></td>
        <td><span class="badge ${catBadge}">${tc.category}</span></td>
        <td>
          <div style="font-weight:700;">${tc.title}</div>
          <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.2rem;">${tc.objective}</div>
        </td>
        <td><span class="badge ${priBadge}">${tc.priority}</span></td>
        <td><span class="badge ${statusBadge}">${tc.review_status}</span></td>
        <td>
          <div style="display:flex; gap:0.35rem; flex-wrap:wrap;">
            <button class="btn btn-success btn-sm" onclick="setTestCaseStatus(${idx + 1}, 'Approved')">Approve</button>
            <button class="btn btn-danger btn-sm" onclick="setTestCaseStatus(${idx + 1}, 'Reject')">Reject</button>
            <button class="btn btn-secondary btn-sm" onclick="openTestCaseModal(${idx})">Edit</button>
            <button class="btn btn-primary btn-sm" onclick="regenerateTestCase(${idx + 1})">Regen</button>
          </div>
        </td>
      </tr>
    `;
    })
    .join("");
}

async function setTestCaseStatus(dbId, status) {
  try {
    const res = await fetch(`${API_BASE}/sdlc/test-cases/${dbId}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ review_status: status }),
    });

    if (res.ok) {
      showToast(`Test case status updated to ${status}.`, "success");
      await loadTestCasesForDoc(currentDocumentId);
      await refreshDashboardMetrics();
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function regenerateTestCase(dbId) {
  setSpinner(true, "Regenerating test case with Gemini...");
  try {
    const res = await fetch(`${API_BASE}/sdlc/test-cases/${dbId}/regenerate`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      showToast("Test case regenerated successfully!", "success");
      await loadTestCasesForDoc(currentDocumentId);
    }
  } catch (e) {
    showToast(e.message, "error");
  } finally {
    setSpinner(false);
  }
}

// Refresh Coverage & Quality Dashboard
async function refreshDashboardMetrics() {
  if (!currentDocumentId || !authToken) return;

  try {
    const res = await fetch(`${API_BASE}/sdlc/documents/${currentDocumentId}/coverage`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (res.ok) {
      const metrics = await res.json();
      renderDashboardScorecard(metrics);
    }

    const traceRes = await fetch(`${API_BASE}/sdlc/documents/${currentDocumentId}/traceability-matrix`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });

    if (traceRes.ok) {
      const trace = await traceRes.json();
      renderTraceabilityMatrix(trace);
    }
  } catch (err) {
    console.error("Dashboard refresh error:", err);
  }
}

function renderDashboardScorecard(m) {
  const elCoverage = document.getElementById("metric-coverage");
  const elReqs = document.getElementById("metric-reqs");
  const elTests = document.getElementById("metric-tests");
  const elAcceptance = document.getElementById("metric-acceptance");

  if (elCoverage) {
    elCoverage.innerText = m.coverage_percentage !== null ? `${m.coverage_percentage}%` : "N/A";
  }
  if (elReqs) {
    elReqs.innerText = `${m.approved_requirements} / ${m.total_requirements}`;
  }
  if (elTests) {
    elTests.innerText = `${m.approved_test_cases} / ${m.total_test_cases}`;
  }
  if (elAcceptance) {
    elAcceptance.innerText = m.human_acceptance_rate !== null ? `${m.human_acceptance_rate}%` : "N/A";
  }
}

function renderTraceabilityMatrix(matrix) {
  const tbody = document.getElementById("traceability-tbody");
  if (!tbody) return;

  if (matrix.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text-muted); padding:2rem;">No traceability records generated yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = matrix
    .map((r) => {
      const covBadge =
        r.coverage_status === "Covered (Approved)"
          ? "badge-approved"
          : r.coverage_status === "In Review (Tests Generated)"
          ? "badge-pending"
          : "badge-rejected";

      const linkedTcs = r.linked_test_cases.map((t) => `<span class="badge" style="background:#1e293b; color:#38bdf8; margin:2px;">${t.id} (${t.category})</span>`).join(" ");

      return `
      <tr>
        <td><strong>${r.requirement_id}</strong></td>
        <td>${r.title}</td>
        <td><span class="badge badge-functional">${r.category}</span></td>
        <td><span class="badge ${covBadge}">${r.coverage_status}</span></td>
        <td>${linkedTcs || '<span style="color:var(--text-muted);">None</span>'}</td>
      </tr>
    `;
    })
    .join("");
}

// Export Triggers
function downloadCSV() {
  if (!currentDocumentId) {
    showToast("Please select a document first.", "error");
    return;
  }
  window.open(`${API_BASE}/sdlc/documents/${currentDocumentId}/export/csv?only_approved=false`, "_blank");
}

function downloadExcel() {
  if (!currentDocumentId) {
    showToast("Please select a document first.", "error");
    return;
  }
  window.open(`${API_BASE}/sdlc/documents/${currentDocumentId}/export/excel?only_approved=false`, "_blank");
}

// Requirement Edit Modal
function openRequirementModal(idx) {
  const req = currentRequirements[idx];
  if (!req) return;

  document.getElementById("modal-req-id").innerText = req.id;
  document.getElementById("edit-req-title").value = req.title;
  document.getElementById("edit-req-desc").value = req.description;
  document.getElementById("edit-req-category").value = req.category;
  document.getElementById("edit-req-status").value = req.review_status;
  document.getElementById("edit-req-original").innerText = req.original_text || "No verbatim text recorded.";
  document.getElementById("edit-req-assumptions").innerText = req.ai_assumptions ? req.ai_assumptions.join("\n") : "None";

  const modal = document.getElementById("req-modal");
  modal.setAttribute("data-db-id", idx + 1);
  modal.classList.add("active");
}

function closeRequirementModal() {
  const modal = document.getElementById("req-modal");
  if (modal) modal.classList.remove("active");
}

async function saveRequirementEdit() {
  const modal = document.getElementById("req-modal");
  const dbId = modal.getAttribute("data-db-id");

  const title = document.getElementById("edit-req-title").value;
  const description = document.getElementById("edit-req-desc").value;
  const category = document.getElementById("edit-req-category").value;
  const review_status = document.getElementById("edit-req-status").value;

  try {
    const res = await fetch(`${API_BASE}/sdlc/requirements/${dbId}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title, description, category, review_status }),
    });

    if (res.ok) {
      showToast("Requirement updated successfully.", "success");
      closeRequirementModal();
      await loadRequirementsForDoc(currentDocumentId);
      await refreshDashboardMetrics();
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

// Test Case Edit Modal
function openTestCaseModal(idx) {
  const tc = currentTestCases[idx];
  if (!tc) return;

  document.getElementById("modal-tc-id").innerText = `${tc.id} (${tc.requirement_id})`;
  document.getElementById("edit-tc-title").value = tc.title;
  document.getElementById("edit-tc-category").value = tc.category;
  document.getElementById("edit-tc-priority").value = tc.priority;
  document.getElementById("edit-tc-status").value = tc.review_status;
  document.getElementById("edit-tc-steps").value = tc.steps ? tc.steps.join("\n") : "";
  document.getElementById("edit-tc-expected").value = tc.expected_result;

  const modal = document.getElementById("tc-modal");
  modal.setAttribute("data-db-id", idx + 1);
  modal.classList.add("active");
}

function closeTestCaseModal() {
  const modal = document.getElementById("tc-modal");
  if (modal) modal.classList.remove("active");
}

async function saveTestCaseEdit() {
  const modal = document.getElementById("tc-modal");
  const dbId = modal.getAttribute("data-db-id");

  const title = document.getElementById("edit-tc-title").value;
  const category = document.getElementById("edit-tc-category").value;
  const priority = document.getElementById("edit-tc-priority").value;
  const review_status = document.getElementById("edit-tc-status").value;
  const steps = document.getElementById("edit-tc-steps").value.split("\n").filter((s) => s.trim());
  const expected_result = document.getElementById("edit-tc-expected").value;

  try {
    const res = await fetch(`${API_BASE}/sdlc/test-cases/${dbId}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${authToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ title, category, priority, review_status, steps, expected_result }),
    });

    if (res.ok) {
      showToast("Test case updated successfully.", "success");
      closeTestCaseModal();
      await loadTestCasesForDoc(currentDocumentId);
      await refreshDashboardMetrics();
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}
