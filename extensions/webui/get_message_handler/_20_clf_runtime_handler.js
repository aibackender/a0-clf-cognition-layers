import { drawProcessStep } from "/js/messages.js";

const STYLE_ID = "cognition-layers-clf-runtime-style";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function ensureClfStyles() {
  if (document.getElementById(STYLE_ID)) {
    return;
  }

  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .process-step.CLF .step-badge,
    .process-group .step-badge.CLF {
      background: linear-gradient(135deg, #34d399 0%, #38bdf8 100%);
      border: 1px solid rgba(56, 189, 248, 0.55);
      color: #082f49;
      text-shadow: none;
      box-shadow: 0 6px 18px rgba(56, 189, 248, 0.18);
    }

    .process-step.CLF .process-step-detail {
      border-left: 2px solid rgba(56, 189, 248, 0.45);
    }

    .process-step.CLF .step-title {
      color: #e2f3ff;
    }

    .clf-step-content {
      display: grid;
      gap: 0.55rem;
      margin-top: 0.1rem;
      white-space: normal;
    }

    .clf-runtime-section {
      display: grid;
      gap: 0.18rem;
    }

    .clf-runtime-label {
      color: #7dd3fc;
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .clf-runtime-text {
      color: rgba(226, 232, 240, 0.95);
      line-height: 1.5;
    }

    .clf-runtime-paragraph {
      color: rgba(226, 232, 240, 0.95);
      line-height: 1.5;
      margin: 0;
    }
  `;
  document.head.appendChild(style);
}

function renderClfBody(content) {
  const lines = String(content || "")
    .replaceAll("\r\n", "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return `<p class="clf-runtime-paragraph">CLF emitted a runtime update for this step.</p>`;
  }

  const chunks = [];
  for (const line of lines) {
    const match = line.match(/^([A-Za-z][A-Za-z _-]*):\s*(.*)$/);
    if (match) {
      chunks.push(`
        <div class="clf-runtime-section">
          <div class="clf-runtime-label">${escapeHtml(match[1])}</div>
          <div class="clf-runtime-text">${escapeHtml(match[2])}</div>
        </div>
      `);
      continue;
    }
    chunks.push(`<p class="clf-runtime-paragraph">${escapeHtml(line)}</p>`);
  }
  return chunks.join("");
}

async function drawClfRuntimeMessage(args) {
  ensureClfStyles();

  const result = drawProcessStep({
    id: args.id,
    title: args.heading || "CLF runtime update",
    code: "CLF",
    classes: ["clf-runtime-step"],
    content: args.content || " ",
    contentClasses: ["clf-step-content"],
    log: { ...args, type: "agent" },
  });

  if (result.content) {
    const replacement = document.createElement("div");
    replacement.className = result.content.className;
    replacement.innerHTML = renderClfBody(args.content);
    result.content.replaceWith(replacement);
    result.content = replacement;
  }

  return result;
}

export default async function registerClfRuntimeHandler(extensionData) {
  if (!extensionData || extensionData.type !== "clf" || extensionData.handler) {
    return;
  }
  extensionData.handler = drawClfRuntimeMessage;
}
