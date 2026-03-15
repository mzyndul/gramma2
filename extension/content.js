let currentElement = null;
let iconEl = null;
let popupEl = null;
let toolbarEl = null;
let contentEl = null;
let pendingRequestId = 0;
let popupTarget = null;
let lastBackend = null;
let activeBackend = null;

// Batch/review state (Step 6)
let reviewItems = [];
let currentReviewIndex = 0;
let mergedBatchSuggestion = null;
let selectionSnapshot = null;
let activeRequestMode = null; // "whole" | "batch" | "progressive"

// Selection-only mode
let selectionRange = null; // { start, end } offsets when working on selected text
let textBaseOffset = 0; // offset within full field where segmented text starts (selection + trim)

// Progressive long-text state (Step 7)
let reviewBlocks = [];
let currentBlockIndex = 0;
let longTextSessionId = 0;
let progressiveBackend = null;
let aggressiveApplyAll = false;
let isApplyingBlock = false;

const WHOLE_TEXT_MAX_CHARS = 300;
const WHOLE_TEXT_MAX_SENTENCES = 3;
const PROGRESSIVE_LONG_TEXT_CHARS = 300;
const PROGRESSIVE_LONG_TEXT_SENTENCES = 4;
const BLOCK_TARGET_MAX_CHARS = 200;
const BLOCK_MAX_SENTENCES = 1;
const QUEUE_DEPTH = { local: 3, codex: 4 };

// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------

function isEditableTextElement(el) {
  if (!el) return false;
  const tag = el.tagName?.toLowerCase();
  if (tag === "textarea") return true;
  if (tag === "input") {
    const type = (el.type || "text").toLowerCase();
    return ["text", "search", "email", "url", "tel", ""].includes(type);
  }
  if (el.isContentEditable) return true;
  return false;
}

function getEditableSurfaceKind(el) {
  if (!el) return "unknown";
  const tag = el.tagName?.toLowerCase();
  if (tag === "input") return "input";
  if (tag === "textarea") return "textarea";
  if (el.contentEditable === "plaintext-only") return "plaintext-contenteditable";
  if (el.isContentEditable) return "rich-contenteditable";
  return "unknown";
}

function isPlainTextSurface(el) {
  const kind = getEditableSurfaceKind(el);
  return kind === "input" || kind === "textarea" || kind === "plaintext-contenteditable";
}

const INLINE_FORMAT_TAGS = new Set([
  "strong", "b", "em", "i", "u", "s", "a", "code", "mark", "span", "sub", "sup",
]);

function selectionCrossesFormattingBoundary(el) {
  if (isPlainTextSurface(el)) return false;

  const sel = document.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;

  const range = sel.getRangeAt(0);
  const startNode = range.startContainer;
  const endNode = range.endContainer;

  // Same text node — always safe
  if (startNode === endNode) return false;

  // Walk up from each text node to the editable root, collecting inline format ancestors
  function getInlineAncestors(node, root) {
    const ancestors = [];
    let current = node.parentElement;
    while (current && current !== root) {
      if (INLINE_FORMAT_TAGS.has(current.tagName.toLowerCase())) {
        ancestors.push(current);
      }
      current = current.parentElement;
    }
    return ancestors;
  }

  const startFormats = getInlineAncestors(startNode, el);
  const endFormats = getInlineAncestors(endNode, el);

  // If either side has formatting the other doesn't, boundary is crossed
  if (startFormats.length !== endFormats.length) return true;
  for (let i = 0; i < startFormats.length; i++) {
    if (startFormats[i] !== endFormats[i]) return true;
  }

  // Also check if any inline format element is partially selected within the range
  const walker = document.createTreeWalker(
    range.commonAncestorContainer,
    NodeFilter.SHOW_ELEMENT,
    {
      acceptNode: (node) =>
        INLINE_FORMAT_TAGS.has(node.tagName.toLowerCase())
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_SKIP,
    }
  );
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (range.intersectsNode(node) && !range.isPointInRange(node, 0)) {
      return true; // partially selected formatting element
    }
  }

  return false;
}

function getDeepActiveElement(root = document) {
  let active = root.activeElement;
  while (active && active.shadowRoot && active.shadowRoot.activeElement) {
    active = active.shadowRoot.activeElement;
  }
  return active;
}

function getTextFromElement(el) {
  if (el.isContentEditable) return el.innerText;
  return el.value;
}

function getSelectedTextFromElement(el) {
  if (el.isContentEditable) {
    const sel = document.getSelection();
    if (!sel || sel.isCollapsed || !el.contains(sel.anchorNode)) return null;
    const text = sel.toString();
    if (!text.trim()) return null;

    // Calculate start offset within the element's text
    const fullText = el.innerText;
    const range = sel.getRangeAt(0);
    const preRange = document.createRange();
    preRange.selectNodeContents(el);
    preRange.setEnd(range.startContainer, range.startOffset);
    const start = preRange.toString().length;
    return { text, start, end: start + text.length };
  }

  const start = el.selectionStart;
  const end = el.selectionEnd;
  if (start === end) return null;
  const text = el.value.slice(start, end);
  if (!text.trim()) return null;
  return { text, start, end };
}

function replaceSelectionInElement(el, replacement) {
  if (!selectionRange) return false;

  if (el.isContentEditable && !isPlainTextSurface(el)) {
    // Rich contenteditable — always block auto-apply.
    // execCommand("insertText") is unreliable: formatting leaks even
    // when the selection doesn't cross boundaries (cursor inherits context).
    console.warn("[gramma2] blocked: rich contenteditable, use fallback");
    return false;
  }

  // Plain text surfaces — safe direct replacement
  if (el.isContentEditable) {
    const sel = document.getSelection();
    if (!sel || sel.rangeCount === 0) {
      const range = createRangeFromOffsets(el, selectionRange.start, selectionRange.end);
      if (!range) return false;
      sel.removeAllRanges();
      sel.addRange(range);
    }
    document.execCommand("insertText", false, replacement);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }

  // input/textarea
  const fullText = el.value;
  el.value =
    fullText.slice(0, selectionRange.start) +
    replacement +
    fullText.slice(selectionRange.end);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
}

function createRangeFromOffsets(el, startOffset, endOffset) {
  const range = document.createRange();
  let charCount = 0;
  let startNode = null, startOff = 0, endNode = null, endOff = 0;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const nodeLen = node.textContent.length;
    if (!startNode && charCount + nodeLen > startOffset) {
      startNode = node;
      startOff = startOffset - charCount;
    }
    if (!endNode && charCount + nodeLen >= endOffset) {
      endNode = node;
      endOff = endOffset - charCount;
      break;
    }
    charCount += nodeLen;
  }
  if (!startNode || !endNode) return null;
  range.setStart(startNode, startOff);
  range.setEnd(endNode, endOff);
  return range;
}

function setTextOnElement(el, text) {
  if (el.isContentEditable) {
    el.innerText = text;
  } else {
    el.value = text;
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getSelectionRect(el) {
  if (el.isContentEditable) {
    const sel = document.getSelection();
    if (sel && !sel.isCollapsed && sel.rangeCount > 0 && el.contains(sel.anchorNode)) {
      const range = sel.getRangeAt(0);
      const rects = range.getClientRects();
      if (rects.length > 0) return rects[rects.length - 1]; // last line of selection
    }
  } else if (el.selectionStart !== el.selectionEnd) {
    // For input/textarea, can't get selection rect easily — fall back to element rect
    return null;
  }
  return null;
}

function positionIcon(el) {
  const selRect = getSelectionRect(el);
  const elRect = el.getBoundingClientRect();

  if (selRect) {
    // Position near the end of the selection, but clamp within the element
    const left = Math.min(selRect.right, elRect.right) - 32 + window.scrollX;
    const top = selRect.bottom - 32 + window.scrollY;
    iconEl.style.left = Math.max(left, elRect.left + window.scrollX) + "px";
    iconEl.style.top = top + "px";
  } else {
    iconEl.style.left = (elRect.right - 32 + window.scrollX) + "px";
    iconEl.style.top = (elRect.bottom - 32 + window.scrollY) + "px";
  }
  iconEl.style.display = "flex";
}

function hideIcon() {
  iconEl.style.display = "none";
}

function hidePopup() {
  cleanupProgressiveSession();
  restoreUserSelectionState();
  popupEl.style.display = "none";
  popupTarget = null;
  activeBackend = null;
  reviewItems = [];
  currentReviewIndex = 0;
  mergedBatchSuggestion = null;
  activeRequestMode = null;
  reviewBlocks = [];
  currentBlockIndex = 0;
  aggressiveApplyAll = false;
  selectionRange = null;
  textBaseOffset = 0;
}

function positionPopup() {
  // Show off-screen to measure
  popupEl.style.visibility = "hidden";
  popupEl.style.display = "block";
  const popupWidth = popupEl.offsetWidth;
  const popupHeight = popupEl.offsetHeight;
  popupEl.style.visibility = "";

  const iconRect = iconEl.getBoundingClientRect();

  // Right edge of popup aligns with right edge of icon
  let left = iconRect.right - popupWidth + window.scrollX;
  if (left < window.scrollX + 8) {
    left = window.scrollX + 8;
  }

  // Bottom of popup touches top of icon
  let top = iconRect.top - popupHeight + window.scrollY;

  // Not enough room above — flip below
  if (top < window.scrollY) {
    top = iconRect.bottom + 4 + window.scrollY;
  }

  popupEl.style.left = left + "px";
  popupEl.style.top = top + "px";
}

function updateToolbarActive() {
  toolbarEl.querySelectorAll(".gramma2-tab:not(.gramma2-tab-regen)").forEach(tab => {
    tab.classList.toggle("gramma2-tab-active", tab.dataset.backend === activeBackend);
  });
}

function buildToolbar() {
  toolbarEl.innerHTML = `
    <div class="gramma2-tab" data-backend="local">Local</div>
    <div class="gramma2-tab" data-backend="codex">Codex</div>
    <div class="gramma2-tab gramma2-tab-regen${lastBackend ? "" : " gramma2-hidden"}" data-backend="${lastBackend || "local"}">&#x1F504;</div>
  `;

  toolbarEl.querySelectorAll(".gramma2-tab").forEach(tab => {
    tab.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
    });
    tab.addEventListener("click", () => {
      const backend = tab.dataset.backend;
      lastBackend = backend;
      activeBackend = backend;
      updateToolbarActive();
      handleBackendClick(backend);
    });
  });
}

function showPopupWithToolbar() {
  if (!currentElement) return;
  const text = getTextFromElement(currentElement).trim();
  if (!text) return;

  popupTarget = currentElement;
  buildToolbar();
  contentEl.innerHTML = '<div class="gramma2-hint">Pick a model above</div>';
  positionPopup();
}


function showLoading() {
  contentEl.innerHTML = `
    <div class="gramma2-loading">
      <div class="gramma2-spinner"></div>
      <span>Improving...</span>
    </div>`;
}

function showError(message) {
  contentEl.innerHTML = `<div class="gramma2-error">${escapeHtml(message)}</div>`;
}

// ---------------------------------------------------------------------------
// Sentence segmentation
// ---------------------------------------------------------------------------

function isProseContent(text) {
  // Must contain at least 2 word characters and look like actual prose,
  // not markdown headers, placeholders, or structural fragments
  const words = text.match(/[a-zA-Z]{2,}/g);
  return words && words.length >= 2;
}

function estimateSentenceSegments(text) {
  if (window.Intl && Intl.Segmenter) {
    const segmenter = new Intl.Segmenter("en", { granularity: "sentence" });
    const rawSegments = [];
    for (const seg of segmenter.segment(text)) {
      rawSegments.push({ segment: seg.segment, index: seg.index });
    }

    // Merge non-prose fragments into the previous or next prose segment
    const segments = [];
    let pending = null; // accumulated non-prose prefix

    for (const seg of rawSegments) {
      const rawText = seg.segment;
      const content = rawText.trim();
      if (!content) continue;

      if (!isProseContent(content)) {
        // Non-prose: accumulate into pending buffer
        if (pending) {
          pending.rawText += rawText;
          pending.endOffset = seg.index + rawText.length;
        } else {
          pending = {
            rawText: rawText,
            startOffset: seg.index,
            endOffset: seg.index + rawText.length,
          };
        }
        continue;
      }

      // Prose segment: prepend any pending non-prose
      let finalRawText = rawText;
      let finalStart = seg.index;
      if (pending) {
        finalRawText = pending.rawText + rawText;
        finalStart = pending.startOffset;
        pending = null;
      }

      const finalContent = finalRawText.trim();
      const leadingWhitespace = finalRawText.slice(0, finalRawText.indexOf(finalContent.charAt(0)));
      const trailingWhitespace = finalRawText.slice(finalRawText.lastIndexOf(finalContent.charAt(finalContent.length - 1)) + 1);
      segments.push({
        rawText: finalRawText,
        content: finalContent,
        startOffset: finalStart,
        endOffset: seg.index + rawText.length,
        leadingWhitespace,
        trailingWhitespace,
      });
    }

    // If there's trailing non-prose, append to last segment
    if (pending && segments.length > 0) {
      const last = segments[segments.length - 1];
      last.rawText += pending.rawText;
      last.endOffset = pending.endOffset;
      last.trailingWhitespace = "";
      const trimmed = last.rawText.trim();
      last.content = trimmed;
    } else if (pending) {
      // Entire text is non-prose — treat as single segment
      const content = pending.rawText.trim();
      if (content) {
        segments.push({
          rawText: pending.rawText,
          content,
          startOffset: pending.startOffset,
          endOffset: pending.endOffset,
          leadingWhitespace: "",
          trailingWhitespace: "",
        });
      }
    }

    return segments;
  }
  // Regex fallback
  const regex = /[^.!?]*[.!?]+[\s]*/g;
  const segments = [];
  let match;
  while ((match = regex.exec(text)) !== null) {
    const rawText = match[0];
    const content = rawText.trim();
    if (!content) continue;
    const leadingWhitespace = rawText.slice(0, rawText.indexOf(content.charAt(0)));
    const trailingWhitespace = rawText.slice(rawText.lastIndexOf(content.charAt(content.length - 1)) + 1);
    segments.push({
      rawText,
      content,
      startOffset: match.index,
      endOffset: match.index + rawText.length,
      leadingWhitespace,
      trailingWhitespace,
    });
  }
  // Capture any trailing text without terminal punctuation
  const covered = segments.length > 0 ? segments[segments.length - 1].endOffset : 0;
  if (covered < text.length) {
    const rawText = text.slice(covered);
    const content = rawText.trim();
    if (content) {
      const leadingWhitespace = rawText.slice(0, rawText.indexOf(content.charAt(0)));
      const trailingWhitespace = rawText.slice(rawText.lastIndexOf(content.charAt(content.length - 1)) + 1);
      segments.push({
        rawText,
        content,
        startOffset: covered,
        endOffset: text.length,
        leadingWhitespace,
        trailingWhitespace,
      });
    }
  }
  return segments;
}

function shouldUseBatchFlow(text, segments) {
  return text.length > WHOLE_TEXT_MAX_CHARS || segments.length >= WHOLE_TEXT_MAX_SENTENCES + 1;
}

function shouldUseProgressiveLongTextFlow(text, segments) {
  return text.length >= PROGRESSIVE_LONG_TEXT_CHARS || segments.length >= PROGRESSIVE_LONG_TEXT_SENTENCES;
}

// ---------------------------------------------------------------------------
// Selection capture/restore for highlighting
// ---------------------------------------------------------------------------

function captureUserSelectionState() {
  if (!popupTarget) return;
  const el = popupTarget;
  if (el.isContentEditable) {
    const sel = document.getSelection();
    if (sel && sel.rangeCount > 0) {
      selectionSnapshot = { type: "contenteditable", range: sel.getRangeAt(0).cloneRange() };
    }
  } else {
    selectionSnapshot = {
      type: "input",
      start: el.selectionStart,
      end: el.selectionEnd,
      scrollTop: el.scrollTop,
    };
  }
}

function restoreUserSelectionState() {
  if (!selectionSnapshot || !popupTarget) return;
  const el = popupTarget;
  try {
    if (selectionSnapshot.type === "input" && !el.isContentEditable) {
      el.setSelectionRange(selectionSnapshot.start, selectionSnapshot.end);
      el.scrollTop = selectionSnapshot.scrollTop;
    } else if (selectionSnapshot.type === "contenteditable" && el.isContentEditable) {
      const sel = document.getSelection();
      sel.removeAllRanges();
      sel.addRange(selectionSnapshot.range);
    }
  } catch (_) {
    // Ignore if element state changed
  }
  selectionSnapshot = null;
}

function highlightReviewItem(item) {
  if (!popupTarget) return;
  const el = popupTarget;
  const absStart = item.startOffset + textBaseOffset;
  const absEnd = item.endOffset + textBaseOffset;
  try {
    if (el.isContentEditable) {
      const sel = document.getSelection();
      const range = document.createRange();
      let charCount = 0;
      let startNode = null, startOff = 0, endNode = null, endOff = 0;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const nodeLen = node.textContent.length;
        if (!startNode && charCount + nodeLen > absStart) {
          startNode = node;
          startOff = absStart - charCount;
        }
        if (!endNode && charCount + nodeLen >= absEnd) {
          endNode = node;
          endOff = absEnd - charCount;
          break;
        }
        charCount += nodeLen;
      }
      if (startNode && endNode) {
        range.setStart(startNode, startOff);
        range.setEnd(endNode, endOff);
        sel.removeAllRanges();
        sel.addRange(range);
      }
    } else {
      el.setSelectionRange(absStart, absEnd);
    }
  } catch (_) {
    // Best-effort highlighting
  }
}

// ---------------------------------------------------------------------------
// Routing: whole-text vs batch vs progressive
// ---------------------------------------------------------------------------

function handleBackendClick(backend) {
  if (!popupTarget) return;

  // Clean up any existing progressive session before starting new flow
  if (activeRequestMode === "progressive") {
    cleanupProgressiveSession();
  }

  // Check for text selection — if user selected text, only check that
  const selected = getSelectedTextFromElement(popupTarget);
  if (selected) {
    selectionRange = { start: selected.start, end: selected.end };
    console.log(`[gramma2] selection mode: ${selected.text.length} chars`);
    const text = selected.text.trim();
    // textBaseOffset = selection start + leading whitespace trimmed
    const leadingTrimmed = selected.text.length - selected.text.trimStart().length;
    textBaseOffset = selected.start + leadingTrimmed;
    const segments = estimateSentenceSegments(text);
    if (shouldUseProgressiveLongTextFlow(text, segments)) {
      startProgressiveReview(backend, segments);
    } else if (shouldUseBatchFlow(text, segments)) {
      generateBatchWithBackend(backend, segments);
    } else {
      generateWithBackend(backend);
    }
    return;
  }

  selectionRange = null;
  const fullRawText = getTextFromElement(popupTarget);
  const leadingTrimmed = fullRawText.length - fullRawText.trimStart().length;
  textBaseOffset = leadingTrimmed;
  const text = fullRawText.trim();
  if (!text) return;

  const segments = estimateSentenceSegments(text);
  if (shouldUseProgressiveLongTextFlow(text, segments)) {
    startProgressiveReview(backend, segments);
  } else if (shouldUseBatchFlow(text, segments)) {
    generateBatchWithBackend(backend, segments);
  } else {
    generateWithBackend(backend);
  }
}

// ---------------------------------------------------------------------------
// Existing whole-text flow
// ---------------------------------------------------------------------------

function generateWithBackend(backend) {
  if (!popupTarget) return;
  const text = selectionRange
    ? getTextFromElement(popupTarget).slice(selectionRange.start, selectionRange.end).trim()
    : getTextFromElement(popupTarget).trim();
  if (!text) return;

  activeRequestMode = "whole";
  const requestId = ++pendingRequestId;
  showLoading();

  chrome.runtime.sendMessage(
    { action: "improve", text: text, backend: backend },
    (response) => {
      if (requestId !== pendingRequestId) return;
      if (response && response.suggestions) {
        showSuggestions(response.suggestions);
      } else {
        showError(response?.error || "Failed to get suggestions");
      }

    }
  );
}

function showSuggestions(suggestions) {
  const isRich = popupTarget && !isPlainTextSurface(popupTarget);
  const isSelection = !!selectionRange;

  contentEl.innerHTML = suggestions.map((s, i) =>
    `<div class="gramma2-suggestion" data-index="${i}">
       ${escapeHtml(s)}
     </div>`
  ).join("");

  contentEl.querySelectorAll(".gramma2-suggestion").forEach((el, i) => {
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
    });
    el.addEventListener("click", () => {
      if (!popupTarget) return;

      if (isSelection) {
        const applied = replaceSelectionInElement(popupTarget, suggestions[i]);
        if (!applied) {
          showRichTextFallback(suggestions[i]);
          return;
        }
      } else if (isRich) {
        // Whole-field on rich contenteditable — show explicit options
        showRichTextFallback(suggestions[i]);
        return;
      } else {
        setTextOnElement(popupTarget, suggestions[i]);
      }
      hidePopup();
    });
  });

  // For whole-field rich contenteditable, add a warning label
  if (isRich && !isSelection) {
    const warning = document.createElement("div");
    warning.className = "gramma2-rich-warning";
    warning.textContent = "Rich text detected — click to see apply options";
    contentEl.prepend(warning);
  }
}

function showRichTextFallback(suggestion) {
  contentEl.innerHTML = `
    <div class="gramma2-rich-fallback">
      <div class="gramma2-rich-fallback-title">Rich text detected</div>
      <div class="gramma2-rich-fallback-subtitle">Auto-apply may change formatting. Choose an option:</div>
      <div class="gramma2-review-suggestion">${escapeHtml(suggestion)}</div>
      <div class="gramma2-review-actions">
        <button class="gramma2-btn-primary gramma2-copy-suggestion">Copy to clipboard</button>
        <button class="gramma2-btn-secondary gramma2-apply-plain">Apply as plain text</button>
        <button class="gramma2-btn-secondary gramma2-cancel">Cancel</button>
      </div>
    </div>`;

  contentEl.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  contentEl.querySelector(".gramma2-copy-suggestion").addEventListener("click", () => {
    navigator.clipboard.writeText(suggestion).then(() => {
      contentEl.querySelector(".gramma2-copy-suggestion").textContent = "Copied!";
      setTimeout(() => hidePopup(), 800);
    });
  });

  contentEl.querySelector(".gramma2-apply-plain").addEventListener("click", () => {
    if (!popupTarget) return;
    if (selectionRange) {
      // Force plain text replacement via innerText manipulation
      const fullText = getTextFromElement(popupTarget);
      const newText =
        fullText.slice(0, selectionRange.start) +
        suggestion +
        fullText.slice(selectionRange.end);
      popupTarget.innerText = newText;
      popupTarget.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      popupTarget.innerText = suggestion;
      popupTarget.dispatchEvent(new Event("input", { bubbles: true }));
    }
    hidePopup();
  });

  contentEl.querySelector(".gramma2-cancel").addEventListener("click", () => {
    hidePopup();
  });
}

// ---------------------------------------------------------------------------
// Batch flow (Step 6)
// ---------------------------------------------------------------------------

function generateBatchWithBackend(backend, segments) {
  if (!popupTarget) return;

  activeRequestMode = "batch";
  const requestId = ++pendingRequestId;
  showLoading();
  captureUserSelectionState();

  const sentences = segments.map(s => s.content);

  chrome.runtime.sendMessage(
    { action: "improve-batch", sentences: sentences, backend: backend },
    (response) => {
      if (requestId !== pendingRequestId) return;
      if (response && response.results) {
        handleBatchResults(response.results, segments);
      } else {
        showError(response?.error || "Failed to get suggestions");
      }

    }
  );
}

function handleBatchResults(results, segments) {
  const enriched = results.map((r, i) => ({
    original: r.original,
    suggestion: r.suggestion,
    startOffset: segments[i].startOffset,
    endOffset: segments[i].endOffset,
    leadingWhitespace: segments[i].leadingWhitespace,
    trailingWhitespace: segments[i].trailingWhitespace,
    status: "pending",
  }));

  const changedItems = enriched.filter(r => r.original !== r.suggestion);

  if (changedItems.length === 0) {
    contentEl.innerHTML = '<div class="gramma2-no-changes">No changes suggested</div>';
    return;
  }

  const fullText = getTextFromElement(popupTarget);
  mergedBatchSuggestion = buildMergedText(fullText, enriched, textBaseOffset);

  if (changedItems.length <= 2) {
    if (selectionRange) {
      // In selection mode, extract just the replaced selection portion
      const selLen = selectionRange.end - selectionRange.start;
      const delta = mergedBatchSuggestion.length - fullText.length;
      const selSuggestion = mergedBatchSuggestion.slice(
        selectionRange.start, selectionRange.end + delta
      );
      showSuggestions([selSuggestion]);
    } else {
      showSuggestions([mergedBatchSuggestion]);
    }
    return;
  }

  reviewItems = changedItems;
  currentReviewIndex = 0;
  showBatchSummary(changedItems.length, mergedBatchSuggestion);
}

function buildMergedText(fullText, enrichedResults, baseOffset) {
  let result = fullText;
  for (let i = enrichedResults.length - 1; i >= 0; i--) {
    const item = enrichedResults[i];
    if (item.original === item.suggestion) continue;
    const replacement = item.leadingWhitespace + item.suggestion + item.trailingWhitespace;
    const absStart = item.startOffset + baseOffset;
    const absEnd = item.endOffset + baseOffset;
    result = result.slice(0, absStart) + replacement + result.slice(absEnd);
  }
  return result;
}

// ---------------------------------------------------------------------------
// Summary UI (Step 6)
// ---------------------------------------------------------------------------

function showBatchSummary(changedCount, mergedText) {
  contentEl.innerHTML = `
    <div class="gramma2-summary">
      <div class="gramma2-summary-title">Found ${changedCount} suggested fixes</div>
      <div class="gramma2-summary-subtitle">Review one by one if you want more control.</div>
      <div class="gramma2-review-actions">
        <button class="gramma2-btn-primary gramma2-apply-all">Apply all</button>
        <button class="gramma2-btn-secondary gramma2-review-fixes">Review fixes</button>
      </div>
    </div>`;

  contentEl.querySelector(".gramma2-apply-all").addEventListener("mousedown", (e) => {
    e.preventDefault();
  });
  contentEl.querySelector(".gramma2-apply-all").addEventListener("click", () => {
    if (!popupTarget) return;
    setTextOnElement(popupTarget, mergedText);
    hidePopup();
  });

  contentEl.querySelector(".gramma2-review-fixes").addEventListener("mousedown", (e) => {
    e.preventDefault();
  });
  contentEl.querySelector(".gramma2-review-fixes").addEventListener("click", () => {
    startReviewFlow();
  });
}

// ---------------------------------------------------------------------------
// Review UI (Step 6 — sentence-level)
// ---------------------------------------------------------------------------

function startReviewFlow() {
  currentReviewIndex = 0;
  showCurrentReviewItem();
}

function showCurrentReviewItem() {
  while (currentReviewIndex < reviewItems.length && reviewItems[currentReviewIndex].status !== "pending") {
    currentReviewIndex++;
  }

  if (currentReviewIndex >= reviewItems.length) {
    showReviewDone();
    return;
  }

  const item = reviewItems[currentReviewIndex];
  const pendingCount = reviewItems.filter(r => r.status === "pending").length;
  const totalChanged = reviewItems.length;
  const currentNum = totalChanged - pendingCount + 1;

  contentEl.innerHTML = `
    <div class="gramma2-review-header">
      <span class="gramma2-review-count">Fix ${currentNum} of ${totalChanged}</span>
    </div>
    <div class="gramma2-review-original">${escapeHtml(item.original)}</div>
    <div class="gramma2-review-suggestion">${escapeHtml(item.suggestion)}</div>
    <div class="gramma2-review-actions">
      <button class="gramma2-btn-secondary gramma2-ignore">Ignore</button>
      <button class="gramma2-btn-primary gramma2-apply">Apply</button>
      <button class="gramma2-btn-secondary gramma2-apply-all-remaining">Apply all remaining</button>
    </div>`;

  contentEl.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  contentEl.querySelector(".gramma2-apply").addEventListener("click", () => {
    applyCurrentReviewItem();
  });
  contentEl.querySelector(".gramma2-ignore").addEventListener("click", () => {
    ignoreCurrentReviewItem();
  });
  contentEl.querySelector(".gramma2-apply-all-remaining").addEventListener("click", () => {
    applyAllRemainingReviewItems();
  });

  highlightReviewItem(item);
}

function applyCurrentReviewItem() {
  const item = reviewItems[currentReviewIndex];
  const fullText = getTextFromElement(popupTarget);
  const replacement = item.leadingWhitespace + item.suggestion + item.trailingWhitespace;
  const absStart = item.startOffset + textBaseOffset;
  const absEnd = item.endOffset + textBaseOffset;
  const newText =
    fullText.slice(0, absStart) +
    replacement +
    fullText.slice(absEnd);

  setTextOnElement(popupTarget, newText);

  const delta = replacement.length - (item.endOffset - item.startOffset);
  item.status = "applied";
  for (let i = currentReviewIndex + 1; i < reviewItems.length; i++) {
    if (reviewItems[i].status !== "pending") continue;
    reviewItems[i].startOffset += delta;
    reviewItems[i].endOffset += delta;
  }

  currentReviewIndex++;
  showCurrentReviewItem();
}

function ignoreCurrentReviewItem() {
  reviewItems[currentReviewIndex].status = "ignored";
  currentReviewIndex++;
  showCurrentReviewItem();
}

function applyAllRemainingReviewItems() {
  if (!popupTarget) return;
  const pending = reviewItems
    .map((item, i) => ({ item, i }))
    .filter(({ item }) => item.status === "pending")
    .reverse();

  let fullText = getTextFromElement(popupTarget);
  for (const { item } of pending) {
    const replacement = item.leadingWhitespace + item.suggestion + item.trailingWhitespace;
    const absStart = item.startOffset + textBaseOffset;
    const absEnd = item.endOffset + textBaseOffset;
    fullText = fullText.slice(0, absStart) + replacement + fullText.slice(absEnd);
    item.status = "applied";
  }
  setTextOnElement(popupTarget, fullText);
  hidePopup();
}

function showReviewDone() {
  contentEl.innerHTML = '<div class="gramma2-done">All done</div>';
  setTimeout(() => {
    if (contentEl.querySelector(".gramma2-done")) {
      hidePopup();
    }
  }, 1500);
}

// ---------------------------------------------------------------------------
// Progressive long-text flow (Step 7)
// ---------------------------------------------------------------------------

function buildReviewBlocks(text, segments) {
  const blocks = [];
  let blockSentences = [];
  let blockStart = null;
  let blockEnd = null;

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];

    if (blockSentences.length === 0) {
      blockStart = seg.startOffset;
      blockEnd = seg.endOffset;
      blockSentences.push(i);
      continue;
    }

    const newLength = seg.endOffset - blockStart;
    if (newLength > BLOCK_TARGET_MAX_CHARS || blockSentences.length >= BLOCK_MAX_SENTENCES) {
      blocks.push({
        blockIndex: blocks.length,
        startOffset: blockStart,
        endOffset: blockEnd,
        originalText: text.slice(blockStart, blockEnd),
        sentenceIndexes: [...blockSentences],
        status: "queued",
        suggestion: null,
        requestId: null,
      });
      blockStart = seg.startOffset;
      blockEnd = seg.endOffset;
      blockSentences = [i];
    } else {
      blockEnd = seg.endOffset;
      blockSentences.push(i);
    }
  }

  if (blockSentences.length > 0) {
    blocks.push({
      blockIndex: blocks.length,
      startOffset: blockStart,
      endOffset: blockEnd,
      originalText: text.slice(blockStart, blockEnd),
      sentenceIndexes: [...blockSentences],
      status: "queued",
      suggestion: null,
      requestId: null,
    });
  }

  return blocks;
}

function startProgressiveReview(backend, segments) {
  cleanupProgressiveSession();

  activeRequestMode = "progressive";
  progressiveBackend = backend;
  longTextSessionId++;
  aggressiveApplyAll = false;

  // Use the same text that was segmented (selection or full field, trimmed)
  const fullRaw = getTextFromElement(popupTarget);
  const text = selectionRange
    ? fullRaw.slice(selectionRange.start, selectionRange.end).trim()
    : fullRaw.trim();
  captureUserSelectionState();

  reviewBlocks = buildReviewBlocks(text, segments);
  currentBlockIndex = 0;

  // Listen for user edits to detect staleness
  popupTarget.addEventListener("input", onProgressiveTargetInput);

  showPreparingLongTextState();
  scheduleMoreBlocks();
}

function onProgressiveTargetInput() {
  if (isApplyingBlock) return;
  invalidateProgressiveSession();
}

function invalidateProgressiveSession() {
  longTextSessionId++;
  reviewBlocks = [];
  currentBlockIndex = 0;
  aggressiveApplyAll = false;
  contentEl.innerHTML = '<div class="gramma2-no-changes">Text changed, refreshing suggestions</div>';
}

function cleanupProgressiveSession() {
  if (popupTarget && activeRequestMode === "progressive") {
    popupTarget.removeEventListener("input", onProgressiveTargetInput);
  }
  progressiveBackend = null;
  aggressiveApplyAll = false;
  isApplyingBlock = false;
}

function getQueueDepth(backend) {
  return QUEUE_DEPTH[backend] || 3;
}

function getResolvedThrough() {
  let resolved = -1;
  for (let i = 0; i < reviewBlocks.length; i++) {
    if (reviewBlocks[i].status === "applied" || reviewBlocks[i].status === "ignored") {
      resolved = i;
    } else {
      break;
    }
  }
  return resolved;
}

function scheduleMoreBlocks() {
  if (aggressiveApplyAll) {
    for (const block of reviewBlocks) {
      if (block.status === "queued") dispatchBlock(block);
    }
    return;
  }

  const resolvedThrough = getResolvedThrough();
  const maxAhead = getQueueDepth(progressiveBackend);

  const aheadCount = reviewBlocks.filter(b =>
    b.blockIndex > resolvedThrough &&
    b.blockIndex <= resolvedThrough + maxAhead &&
    (b.status === "ready" || b.status === "in_flight")
  ).length;

  let available = maxAhead - aheadCount;
  if (available <= 0) return;

  for (const block of reviewBlocks) {
    if (available <= 0) break;
    if (block.blockIndex <= resolvedThrough) continue;
    if (block.blockIndex > resolvedThrough + maxAhead) break;
    if (block.status !== "queued") continue;
    dispatchBlock(block);
    available--;
  }
}

function dispatchBlock(block) {
  if (block.status !== "queued") {
    console.warn(`[gramma2] skip dispatch block ${block.blockIndex} — status is ${block.status}`);
    return;
  }
  block.status = "in_flight";
  const sessionId = longTextSessionId;
  console.log(`[gramma2] dispatch block ${block.blockIndex} (session ${sessionId})`);

  chrome.runtime.sendMessage(
    {
      action: "improve-block",
      text: block.originalText,
      backend: progressiveBackend,
      sessionId: sessionId,
      blockIndex: block.blockIndex,
    },
    (response) => {
      if (sessionId !== longTextSessionId) return;
      if (response && response.suggestion) {
        console.log(`[gramma2] block ${response.blockIndex} ready`);
        handleReadyBlock(response.blockIndex, response.suggestion);
      } else {
        block.status = "failed";
        console.warn(`[gramma2] block ${block.blockIndex} failed`);
        if (block.blockIndex === currentBlockIndex) {
          showBlockError(block);
        }
      }
      scheduleMoreBlocks();

    }
  );
}

function handleReadyBlock(blockIndex, suggestion) {
  const block = reviewBlocks[blockIndex];
  if (!block) return;

  // Auto-ignore unchanged blocks
  if (block.originalText.trim() === suggestion.trim()) {
    block.status = "ignored";
  } else {
    block.status = "ready";
    block.suggestion = suggestion;
  }

  if (aggressiveApplyAll) {
    const pending = reviewBlocks.filter(b => b.status === "queued" || b.status === "in_flight");
    if (pending.length === 0) {
      finishAggressiveApplyAll();
    } else {
      showAggressiveProgress();
    }
    return;
  }

  // If in preparing state, try to show first reviewable block
  if (contentEl.querySelector(".gramma2-preparing")) {
    skipToNextReviewableBlock();
    return;
  }

  // If user is waiting for the current block
  if (contentEl.querySelector(".gramma2-waiting")) {
    if (blockIndex === currentBlockIndex) {
      if (block.status === "ready") {
        showCurrentReadyBlock();
      } else {
        // Auto-ignored, advance
        moveToNextBlock();
      }
    } else {
      // Update the waiting progress display
      showWaitingState();
    }
    return;
  }

  // Update the cached-ahead label if user is reviewing a block
  const readyLabel = contentEl.querySelector(".gramma2-review-ready");
  if (readyLabel) {
    const cachedAhead = reviewBlocks.filter(b =>
      b.blockIndex > currentBlockIndex && b.status === "ready"
    ).length;
    readyLabel.textContent = cachedAhead > 0 ? `${cachedAhead} next ready` : "prefetching...";
  }
}

function skipToNextReviewableBlock() {
  while (currentBlockIndex < reviewBlocks.length) {
    const block = reviewBlocks[currentBlockIndex];
    if (block.status === "ready") {
      showCurrentReadyBlock();
      return;
    }
    if (block.status === "ignored" || block.status === "applied") {
      currentBlockIndex++;
      continue;
    }
    // queued or in_flight — wait
    showWaitingState();
    return;
  }
  // All blocks processed — check if any had user-visible changes
  const anyReviewed = reviewBlocks.some(b => b.suggestion !== null);
  if (anyReviewed) {
    showReviewDone();
  } else {
    contentEl.innerHTML = '<div class="gramma2-no-changes">No changes suggested</div>';
  }
}

function showPreparingLongTextState() {
  const totalBlocks = reviewBlocks.length;
  contentEl.innerHTML = `
    <div class="gramma2-preparing">
      <div class="gramma2-loading">
        <div class="gramma2-spinner"></div>
        <span>Preparing fixes...</span>
      </div>
      <div class="gramma2-preparing-subtitle">Analyzing long text in parts (${totalBlocks} blocks)</div>
    </div>`;
}

function showCurrentReadyBlock() {
  const block = reviewBlocks[currentBlockIndex];
  if (!block || block.status !== "ready") return;

  const totalBlocks = reviewBlocks.length;
  const cachedAhead = reviewBlocks.filter(b =>
    b.blockIndex > currentBlockIndex && b.status === "ready"
  ).length;
  const cachedLabel = cachedAhead > 0 ? `${cachedAhead} next ready` : "prefetching...";

  contentEl.innerHTML = `
    <div class="gramma2-review-header">
      <span class="gramma2-review-count">Fix block ${currentBlockIndex + 1} of ${totalBlocks}</span>
      <span class="gramma2-review-ready">${cachedLabel}</span>
    </div>
    <div class="gramma2-review-original">${escapeHtml(block.originalText)}</div>
    <div class="gramma2-review-suggestion">${escapeHtml(block.suggestion)}</div>
    <div class="gramma2-review-actions">
      <button class="gramma2-btn-secondary gramma2-ignore">Ignore</button>
      <button class="gramma2-btn-primary gramma2-apply">Apply</button>
      <button class="gramma2-btn-secondary gramma2-apply-all-remaining">Apply all remaining</button>
    </div>`;

  contentEl.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  contentEl.querySelector(".gramma2-apply").addEventListener("click", () => applyCurrentBlock());
  contentEl.querySelector(".gramma2-ignore").addEventListener("click", () => ignoreCurrentBlock());
  contentEl.querySelector(".gramma2-apply-all-remaining").addEventListener("click", () => applyAllRemainingBlocks());

  highlightReviewItem(block);
}

function showWaitingState() {
  const totalBlocks = reviewBlocks.length;
  const readyCount = reviewBlocks.filter(b =>
    b.status === "ready" || b.status === "applied" || b.status === "ignored"
  ).length;

  contentEl.innerHTML = `
    <div class="gramma2-waiting">
      <div class="gramma2-loading">
        <div class="gramma2-spinner"></div>
        <span>Preparing next fixes...</span>
      </div>
      <div class="gramma2-waiting-progress">${readyCount} of ${totalBlocks} blocks ready</div>
    </div>`;
}

function showBlockError(block) {
  contentEl.innerHTML = `
    <div class="gramma2-review-header">
      <span class="gramma2-review-count">Block ${block.blockIndex + 1} failed</span>
    </div>
    <div class="gramma2-review-original">${escapeHtml(block.originalText)}</div>
    <div class="gramma2-error">Failed to process this block</div>
    <div class="gramma2-review-actions">
      <button class="gramma2-btn-secondary gramma2-ignore">Ignore</button>
      <button class="gramma2-btn-primary gramma2-retry">Retry</button>
    </div>`;

  contentEl.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("mousedown", (e) => e.preventDefault());
  });

  contentEl.querySelector(".gramma2-retry").addEventListener("click", () => {
    block.status = "queued";
    dispatchBlock(block);
    showWaitingState();
  });
  contentEl.querySelector(".gramma2-ignore").addEventListener("click", () => {
    block.status = "ignored";
    moveToNextBlock();
  });
}

function applyCurrentBlock() {
  const block = reviewBlocks[currentBlockIndex];
  const fullText = getTextFromElement(popupTarget);
  const absStart = block.startOffset + textBaseOffset;
  const absEnd = block.endOffset + textBaseOffset;
  const newText =
    fullText.slice(0, absStart) +
    block.suggestion +
    fullText.slice(absEnd);

  isApplyingBlock = true;
  setTextOnElement(popupTarget, newText);
  isApplyingBlock = false;

  const delta = block.suggestion.length - (block.endOffset - block.startOffset);
  block.status = "applied";

  // Update offsets of all later blocks
  for (let i = block.blockIndex + 1; i < reviewBlocks.length; i++) {
    reviewBlocks[i].startOffset += delta;
    reviewBlocks[i].endOffset += delta;
  }

  moveToNextBlock();
}

function ignoreCurrentBlock() {
  reviewBlocks[currentBlockIndex].status = "ignored";
  moveToNextBlock();
}

function moveToNextBlock() {
  currentBlockIndex++;
  scheduleMoreBlocks();
  skipToNextReviewableBlock();
}

function applyAllRemainingBlocks() {
  if (!popupTarget) return;

  const pending = reviewBlocks.filter(b => b.status === "queued" || b.status === "in_flight");
  if (pending.length === 0) {
    // All blocks ready — apply now
    finishAggressiveApplyAll();
    return;
  }

  // Switch to aggressive mode
  aggressiveApplyAll = true;
  scheduleMoreBlocks();
  showAggressiveProgress();
}

function showAggressiveProgress() {
  const totalBlocks = reviewBlocks.length;
  const readyCount = reviewBlocks.filter(b =>
    b.status === "ready" || b.status === "applied" || b.status === "ignored"
  ).length;

  contentEl.innerHTML = `
    <div class="gramma2-aggressive">
      <div class="gramma2-loading">
        <div class="gramma2-spinner"></div>
        <span>Finishing remaining fixes...</span>
      </div>
      <div class="gramma2-aggressive-progress">${readyCount} of ${totalBlocks} blocks ready</div>
    </div>`;
}

function finishAggressiveApplyAll() {
  if (!popupTarget) return;

  // Apply all ready blocks from end to start
  const toApply = reviewBlocks
    .filter(b => b.status === "ready")
    .reverse();

  let fullText = getTextFromElement(popupTarget);
  for (const block of toApply) {
    const absStart = block.startOffset + textBaseOffset;
    const absEnd = block.endOffset + textBaseOffset;
    fullText = fullText.slice(0, absStart) + block.suggestion + fullText.slice(absEnd);
    block.status = "applied";
  }

  isApplyingBlock = true;
  setTextOnElement(popupTarget, fullText);
  isApplyingBlock = false;

  hidePopup();
}

// ---------------------------------------------------------------------------
// Initialize DOM elements
// ---------------------------------------------------------------------------

iconEl = document.createElement("div");
iconEl.className = "gramma2-icon";
iconEl.innerHTML = "G";
iconEl.style.display = "none";
document.body.appendChild(iconEl);

popupEl = document.createElement("div");
popupEl.className = "gramma2-popup";
popupEl.style.display = "none";

toolbarEl = document.createElement("div");
toolbarEl.className = "gramma2-toolbar";
popupEl.appendChild(toolbarEl);

contentEl = document.createElement("div");
contentEl.className = "gramma2-content";
popupEl.appendChild(contentEl);

document.body.appendChild(popupEl);

// Focus tracking
document.addEventListener("focusin", (e) => {
  const target = getDeepActiveElement() || e.target;
  if (isEditableTextElement(target)) {
    currentElement = target;
    positionIcon(target);
  }
});

// Reposition icon when selection changes within an editable element
document.addEventListener("selectionchange", () => {
  if (!currentElement || popupEl.style.display !== "none") return;
  positionIcon(currentElement);
});

document.addEventListener("focusout", (e) => {
  const blurredElement = e.target;
  setTimeout(() => {
    if (currentElement && currentElement !== blurredElement) return;
    const active = document.activeElement;
    if (iconEl.contains(active) || popupEl.contains(active)) return;
    if (iconEl.matches(":hover") || popupEl.matches(":hover")) return;
    const nextActive = getDeepActiveElement();
    if (isEditableTextElement(nextActive)) {
      currentElement = nextActive;
      positionIcon(nextActive);
      return;
    }
    hideIcon();
    hidePopup();
    currentElement = null;
  }, 100);
});

// Icon click — prevent focus loss
iconEl.addEventListener("mousedown", (e) => {
  e.preventDefault();
  e.stopPropagation();
});

iconEl.addEventListener("click", () => {
  showPopupWithToolbar();
});

// Click-outside dismissal
document.addEventListener("mousedown", (e) => {
  if (popupEl.style.display !== "none" &&
      !popupEl.contains(e.target) &&
      !iconEl.contains(e.target)) {
    hidePopup();
  }
});
