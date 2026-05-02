(function () {
  var prompt = document.getElementById("prompt");
  var messages = document.getElementById("messages");
  var status = document.getElementById("status");
  var historyList = document.getElementById("historyList");
  var composerForm = document.getElementById("composerForm");
  var sendButton = document.getElementById("sendButton");
  var statusBadge = document.getElementById("statusBadge");
  var statusDetail = document.getElementById("statusDetail");
  var modeName = document.getElementById("modeName");
  var referenceList = document.getElementById("referenceList");
  var toggleReferences = document.getElementById("toggleReferences");
  var clearHistoryButton = document.getElementById("clearHistoryButton");
  var starterRow = document.getElementById("starterRow");
  var typingTimer = null;
  var scrollRestoreKey = "mlpxplorer_scroll_restore_modern";
  var shouldStickToBottom = true;
  var autoScrollLocked = false;
  var activeReferenceTurnId = "";
  var ICON_EDIT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.25V20h3.75L18.8 8.94l-3.75-3.75L4 16.25Zm13.65-8.39 1.69-1.69a1 1 0 0 0 0-1.41l-1.79-1.79a1 1 0 0 0-1.41 0l-1.69 1.69 3.2 3.2Z" fill="currentColor"/></svg>';
  var ICON_COPY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h3Zm2 0h6a2 2 0 0 1 2 2v4h1V5h-9v3Zm6 11v-9H5v9h11Z" fill="currentColor"/></svg>';

  if (!prompt || !messages || !status || !historyList || !composerForm || !sendButton) {
    return;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function actionIcon(action) {
    return action === "edit" ? ICON_EDIT : ICON_COPY;
  }

  function normalizeActionButtons(root) {
    var scope = root || document;
    var buttons = scope.querySelectorAll(".msg-action[data-action]");
    var i;
    var action;
    for (i = 0; i < buttons.length; i += 1) {
      action = buttons[i].getAttribute("data-action");
      if (action === "edit" || action === "copy") {
        buttons[i].innerHTML = actionIcon(action);
        buttons[i].classList.add("icon-action");
      }
    }
  }

  function updateSessionId(sessionId) {
    var inputs = document.querySelectorAll('input[name="session_id"]');
    var i;
    for (i = 0; i < inputs.length; i += 1) {
      inputs[i].value = sessionId;
    }
    if (window.__MLPXPLORER__) {
      window.__MLPXPLORER__.sessionId = sessionId;
    }
  }

  function updatePromptHistory(html) {
    if (typeof html === "string") {
      historyList.innerHTML = html;
    }
  }

  function updateStarterHtml(html) {
    if (starterRow && typeof html === "string") {
      starterRow.innerHTML = html;
    }
  }

  function isNearPageBottom() {
    var scrollTop;
    var viewport;
    var fullHeight;

    if (!messages) {
      return true;
    }

    scrollTop = messages.scrollTop || 0;
    viewport = messages.clientHeight || 0;
    fullHeight = messages.scrollHeight || 0;
    return fullHeight - (scrollTop + viewport) < 120;
  }

  function scrollPageToBottom(behavior, force) {
    if (!force && (!shouldStickToBottom || autoScrollLocked)) {
      return;
    }

    if (!messages) {
      return;
    }

    if ((behavior || "auto") === "smooth" && typeof messages.scrollTo === "function") {
      messages.scrollTo({
        top: messages.scrollHeight || 0,
        behavior: "smooth"
      });
      return;
    }

    messages.scrollTop = messages.scrollHeight || 0;
  }

  function syncScrollIntent() {
    shouldStickToBottom = isNearPageBottom();
  }

  function rememberScrollRestore(mode) {
    try {
      window.sessionStorage.setItem(scrollRestoreKey, mode);
    } catch (error) {
      return;
    }
  }

  function restoreScrollIfNeeded() {
    var mode;
    try {
      mode = window.sessionStorage.getItem(scrollRestoreKey);
      if (!mode) {
        return;
      }
      window.sessionStorage.removeItem(scrollRestoreKey);
    } catch (error) {
      return;
    }
    if (mode === "bottom") {
      window.setTimeout(function () {
        scrollPageToBottom("auto", true);
      }, 0);
    }
  }

  function stripRenderedReferences(html) {
    var wrapper;
    var headings;
    var i;
    var headingText;
    var node;
    var next;

    if (typeof html !== "string" || html.indexOf("References") === -1) {
      return html;
    }

    wrapper = document.createElement("div");
    wrapper.innerHTML = html;
    headings = wrapper.querySelectorAll("h1, h2, h3, h4, p, strong");

    for (i = 0; i < headings.length; i += 1) {
      headingText = (headings[i].textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (headingText === "references") {
        node = headings[i];
        next = node.nextSibling;
        node.remove();
        while (next) {
          node = next;
          next = next.nextSibling;
          node.remove();
        }
        return wrapper.innerHTML;
      }
    }

    return html;
  }

  function splitAnswerAndReferences(text) {
    var value = String(text || "").replace(/\r\n/g, "\n");
    var lines = value.split("\n");
    var refs = [];
    var bodyLines = [];
    var inReferences = false;
    var currentRef = null;
    var i;
    var line;
    var trimmed;
    var match;

    for (i = 0; i < lines.length; i += 1) {
      line = lines[i];
      trimmed = line.replace(/^\s+|\s+$/g, "");

      if (!inReferences && /^((#{1,6}\s*)|(\*\*\s*))?references((\s*\*\*)?)\s*:?$/i.test(trimmed)) {
        inReferences = true;
        continue;
      }

      if (!inReferences) {
        bodyLines.push(line);
        continue;
      }

      match = trimmed.match(/^\[(\d+)\]\s+(.*)$/);
      if (match) {
        if (currentRef) {
          refs.push(currentRef);
        }
        currentRef = {
          number: match[1],
          text: match[2]
        };
        continue;
      }

      if (!trimmed) {
        if (currentRef) {
          refs.push(currentRef);
          currentRef = null;
        }
        continue;
      }

      if (currentRef) {
        currentRef.text += " " + trimmed;
      }
    }

    if (currentRef) {
      refs.push(currentRef);
    }

    return {
      bodyText: bodyLines.join("\n").replace(/\s+$/, ""),
      references: refs
    };
  }

  function stripReferenceTextBlock(text) {
    return splitAnswerAndReferences(text).bodyText;
  }

  function stripRenderedFallbackNotice(html) {
    var wrapper;
    var first;
    var second;
    var firstText;

    if (typeof html !== "string" || html.indexOf("DeepSeek Unavailable") === -1) {
      return html;
    }

    wrapper = document.createElement("div");
    wrapper.innerHTML = html;

    while (wrapper.firstChild && wrapper.firstChild.nodeType === 3 && !String(wrapper.firstChild.textContent || "").replace(/\s+/g, "")) {
      wrapper.removeChild(wrapper.firstChild);
    }

    first = wrapper.firstElementChild;
    if (!first) {
      return html;
    }

    firstText = (first.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (firstText === "deepseek unavailable") {
      second = first.nextElementSibling;
      first.remove();
      if (second) {
        firstText = (second.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (firstText.indexOf("the following answer was generated") === 0 || firstText.indexOf("reason:") === 0) {
          second.remove();
        }
      }
      return wrapper.innerHTML;
    }

    return html;
  }

  function cleanupAssistantReferenceBlocks() {
    var assistantBodies = messages.querySelectorAll(".msg.assistant .msg-body");
    var i;
    for (i = 0; i < assistantBodies.length; i += 1) {
      assistantBodies[i].innerHTML = stripRenderedFallbackNotice(
        stripRenderedReferences(assistantBodies[i].innerHTML)
      );
    }
  }

  function updateStarterVisibility() {
    if (!starterRow) {
      return;
    }
    starterRow.style.display = "flex";
  }

  function updateMessages(html) {
    if (typeof html === "string") {
      messages.innerHTML = html;
      cleanupAssistantReferenceBlocks();
      normalizeActionButtons(messages);
      refreshReferencePanel();
      updateStarterVisibility();
      scrollPageToBottom("auto", true);
    }
  }

  function updateDraft(value) {
    if (typeof value === "string") {
      prompt.value = value;
    }
  }

  function setStatusChrome(text) {
    var normalized = String(text || "Ready.");
    var lowered = normalized.toLowerCase();
    var fallback = lowered.indexOf("unavailable") !== -1 || lowered.indexOf("local-only") !== -1 || lowered.indexOf("local only") !== -1;

    status.textContent = normalized;
    if (statusDetail) {
      statusDetail.textContent = normalized;
    }
    if (modeName) {
      modeName.textContent = fallback ? "Fallback (Local KB)" : "LLM + Local KB";
    }
    if (statusBadge) {
      statusBadge.textContent = fallback ? "Fallback Mode | DeepSeek Unavailable" : "Connected Mode (LLM + Local KB)";
      statusBadge.classList.toggle("is-live", !fallback);
    }
  }

  function createUserMessageElement(text) {
    var wrapper = document.createElement("div");
    wrapper.className = "msg user";
    wrapper.setAttribute("data-role", "user");
    wrapper.setAttribute("data-raw", text);
    wrapper.innerHTML =
      '<div class="msg-body"><p>' + escapeHtml(text) + '</p></div>' +
      '<div class="msg-actions">' +
      '<button class="msg-action secondary icon-action" type="button" data-action="edit" aria-label="Edit prompt" title="Edit prompt">' + ICON_EDIT + '</button>' +
      '<button class="msg-action secondary icon-action" type="button" data-action="copy" aria-label="Copy prompt" title="Copy prompt">' + ICON_COPY + '</button>' +
      "</div>";
    return wrapper;
  }

  function createAssistantPlaceholder() {
    var wrapper = document.createElement("div");
    wrapper.className = "msg assistant";
    wrapper.setAttribute("data-role", "assistant");
    wrapper.setAttribute("data-raw", "");
    wrapper.innerHTML =
      '<div class="msg-body"><p class="typing-indicator">Writing response</p></div>' +
      '<div class="msg-actions">' +
      '<button class="msg-action secondary icon-action" type="button" data-action="copy" aria-label="Copy response" title="Copy response">' + ICON_COPY + '</button>' +
      "</div>";
    return wrapper;
  }

  function formatInline(value) {
    var html = escapeHtml(value);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    return html;
  }

  function isMarkdownTableRow(text) {
    return /^\|.*\|$/.test(text);
  }

  function isMarkdownTableSeparator(text) {
    var compact = text.replace(/\s+/g, "");
    return /^\|?[:\-|]+\|?$/.test(compact) && compact.indexOf("-") !== -1;
  }

  function splitMarkdownTableRow(text) {
    return text
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map(function (cell) {
        return cell.replace(/^\s+|\s+$/g, "");
      });
  }

  function renderRichText(text) {
    var lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    var parts = [];
    var inList = false;
    var inOrdered = false;
    var inCode = false;
    var codeLines = [];
    var i;

    function closeLists() {
      if (inList) {
        parts.push("</ul>");
        inList = false;
      }
      if (inOrdered) {
        parts.push("</ol>");
        inOrdered = false;
      }
    }

    function flushCode() {
      if (inCode) {
        parts.push("<pre><code>" + escapeHtml(codeLines.join("\n")) + "</code></pre>");
        inCode = false;
        codeLines = [];
      }
    }

    for (i = 0; i < lines.length; i += 1) {
      var rawLine = lines[i];
      var trimmed = rawLine.replace(/^\s+|\s+$/g, "");
      var headingMatch;
      var headerCells;
      var bodyRows;
      var rowIndex;
      var colIndex;

      if (trimmed.indexOf("```") === 0) {
        closeLists();
        if (inCode) {
          flushCode();
        } else {
          inCode = true;
        }
        continue;
      }

      if (inCode) {
        codeLines.push(rawLine);
        continue;
      }

      if (!trimmed) {
        closeLists();
        continue;
      }

      if (
        isMarkdownTableRow(trimmed) &&
        i + 1 < lines.length &&
        isMarkdownTableSeparator(lines[i + 1].replace(/^\s+|\s+$/g, ""))
      ) {
        closeLists();
        headerCells = splitMarkdownTableRow(trimmed);
        bodyRows = [];
        i += 2;
        while (i < lines.length) {
          trimmed = lines[i].replace(/^\s+|\s+$/g, "");
          if (!trimmed || !isMarkdownTableRow(trimmed) || isMarkdownTableSeparator(trimmed)) {
            i -= 1;
            break;
          }
          bodyRows.push(splitMarkdownTableRow(trimmed));
          i += 1;
        }
        parts.push('<div class="table-wrap"><table><thead><tr>');
        for (colIndex = 0; colIndex < headerCells.length; colIndex += 1) {
          parts.push("<th>" + formatInline(headerCells[colIndex]) + "</th>");
        }
        parts.push("</tr></thead><tbody>");
        for (rowIndex = 0; rowIndex < bodyRows.length; rowIndex += 1) {
          parts.push("<tr>");
          for (colIndex = 0; colIndex < headerCells.length; colIndex += 1) {
            parts.push("<td>" + formatInline(bodyRows[rowIndex][colIndex] || "") + "</td>");
          }
          parts.push("</tr>");
        }
        parts.push("</tbody></table></div>");
        continue;
      }

      if ((/^\$\$.*\$\$$/).test(trimmed) || (trimmed.indexOf("\\[") === 0 && trimmed.slice(-2) === "\\]")) {
        closeLists();
        parts.push('<div class="equation">' + escapeHtml(trimmed) + "</div>");
        continue;
      }

      headingMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
      if (headingMatch) {
        closeLists();
        parts.push("<h" + Math.min(headingMatch[1].length, 4) + ">" + formatInline(headingMatch[2]) + "</h" + Math.min(headingMatch[1].length, 4) + ">");
        continue;
      }

      if ((/^>\s+/).test(trimmed)) {
        closeLists();
        parts.push("<blockquote>" + formatInline(trimmed.replace(/^>\s+/, "")) + "</blockquote>");
        continue;
      }

      if ((/^[-*]\s+/).test(trimmed)) {
        if (inOrdered) {
          parts.push("</ol>");
          inOrdered = false;
        }
        if (!inList) {
          parts.push("<ul>");
          inList = true;
        }
        parts.push("<li>" + formatInline(trimmed.replace(/^[-*]\s+/, "")) + "</li>");
        continue;
      }

      if ((/^\d+\.\s+/).test(trimmed)) {
        if (inList) {
          parts.push("</ul>");
          inList = false;
        }
        if (!inOrdered) {
          parts.push("<ol>");
          inOrdered = true;
        }
        parts.push("<li>" + formatInline(trimmed.replace(/^\d+\.\s+/, "")) + "</li>");
        continue;
      }

      closeLists();
      parts.push("<p>" + formatInline(trimmed) + "</p>");
    }

    flushCode();
    closeLists();
    return parts.join("");
  }

  function extractReferencesFromText(raw) {
    var parsed = splitAnswerAndReferences(raw);
    return parsed.references.map(function (ref) {
      return {
        number: ref.number,
        text: String(ref.text || "").replace(/\s{2,}/g, " ").replace(/\*\*/g, "").trim()
      };
    });
  }

  function getAssistantRawForTurn(turnId) {
    var turn;
    var assistant;

    if (!turnId) {
      return "";
    }

    turn = document.getElementById(turnId);
    if (!turn) {
      return "";
    }

    assistant = turn.querySelector('.msg.assistant[data-raw]');
    return assistant ? (assistant.getAttribute("data-raw") || "") : "";
  }

  function setActiveReferenceTurn(turnId) {
    var items = historyList ? historyList.querySelectorAll("[data-target]") : [];
    var i;

    activeReferenceTurnId = turnId || "";
    for (i = 0; i < items.length; i += 1) {
      items[i].classList.toggle("is-selected", items[i].getAttribute("data-target") === activeReferenceTurnId);
    }
  }

  function refreshReferencePanel(rawOverride) {
    var assistants;
    var latest;
    var refs;
    var parts = [];
    var i;

    latest = typeof rawOverride === "string" ? rawOverride : "";
    if (!latest && activeReferenceTurnId) {
      latest = getAssistantRawForTurn(activeReferenceTurnId);
    }
    if (!latest) {
      assistants = messages.querySelectorAll('.msg.assistant[data-raw]');
      latest = assistants.length ? assistants[assistants.length - 1].getAttribute("data-raw") : "";
    }

    if (!referenceList) {
      return;
    }

    refs = extractReferencesFromText(latest);

    if (!refs.length) {
      referenceList.innerHTML = '<div class="reference-empty">References from the latest assistant response will appear here.</div>';
      return;
    }

    for (i = 0; i < refs.length; i += 1) {
      parts.push(
        '<article class="reference-item">' +
          '<div class="reference-index">' + escapeHtml(refs[i].number) + '</div>' +
          '<div class="reference-text">[' + escapeHtml(refs[i].number) + '] ' + escapeHtml(refs[i].text) + '</div>' +
        '</article>'
      );
    }
    referenceList.innerHTML = parts.join("");
  }

  function animateAssistantResponse(placeholder, text, finalHtml, onDone) {
    var body = placeholder.querySelector(".msg-body");
    var content = String(text || "");
    var separated = splitAnswerAndReferences(content);
    var displayContent = separated.bodyText;
    var index = 0;
    var step = Math.max(2, Math.ceil(displayContent.length / 140));

    placeholder.setAttribute("data-raw", content);

    if (typingTimer) {
      window.clearInterval(typingTimer);
      typingTimer = null;
    }

    body.textContent = "";
    typingTimer = window.setInterval(function () {
      index += step;
      body.innerHTML = renderRichText(displayContent.slice(0, index));
      scrollPageToBottom("auto");
      if (index >= displayContent.length) {
        window.clearInterval(typingTimer);
        typingTimer = null;
        body.innerHTML = stripRenderedFallbackNotice(
          stripRenderedReferences(finalHtml || ("<p>" + escapeHtml(content) + "</p>"))
        );
        normalizeActionButtons(placeholder);
        updateStarterVisibility();
        refreshReferencePanel();
        scrollPageToBottom("auto");
        if (typeof onDone === "function") {
          onDone();
        }
      }
    }, 18);
  }

  function setBusy(isBusy, label) {
    sendButton.disabled = !!isBusy;
    sendButton.textContent = isBusy ? (label || "...") : "Send";
  }

  function serializeForm(form) {
    var pairs = [];
    var elements = form.elements;
    var i;
    for (i = 0; i < elements.length; i += 1) {
      var element = elements[i];
      if (!element.name || element.disabled) {
        continue;
      }
      if ((element.type === "checkbox" || element.type === "radio") && !element.checked) {
        continue;
      }
      pairs.push(encodeURIComponent(element.name) + "=" + encodeURIComponent(element.value));
    }
    return pairs.join("&");
  }

  function postForm(form, onSuccess, onFailure) {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", form.action, true);
    xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
    xhr.onreadystatechange = function () {
      var payload;
      if (xhr.readyState !== 4) {
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        onFailure("HTTP " + xhr.status);
        return;
      }
      try {
        payload = JSON.parse(xhr.responseText);
      } catch (error) {
        onFailure("Invalid JSON response");
        return;
      }
      onSuccess(payload);
    };
    xhr.onerror = function () {
      onFailure("Network error");
    };
    xhr.send(serializeForm(form));
  }

  function applyUiState(payload) {
    if (typeof payload.session_id === "string") {
      updateSessionId(payload.session_id);
    }
    updateMessages(payload.messages_html);
    updatePromptHistory(payload.prompt_history_html);
    updateStarterHtml(payload.starter_html);
    normalizeActionButtons(messages);
    updateDraft(payload.draft);
    updateStarterVisibility();
    setStatusChrome(payload.status || "Ready.");
  }

  function submitClearedComposerFallback(submittedText) {
    var hiddenMessage = document.createElement("input");
    var originalName = prompt.getAttribute("name");
    hiddenMessage.type = "hidden";
    hiddenMessage.name = originalName || "message";
    hiddenMessage.value = submittedText;
    composerForm.appendChild(hiddenMessage);
    prompt.value = "";
    prompt.removeAttribute("name");
    rememberScrollRestore("bottom");
    composerForm.submit();
  }

  function finishSubmission() {
    setBusy(false);
    prompt.focus();
  }

  function copyText(value) {
    var helper;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }
    helper = document.createElement("textarea");
    helper.value = value;
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    document.body.removeChild(helper);
    return null;
  }

  function flashButtonLabel(button, label) {
    var original = button.getAttribute("data-original-label");
    if (!original) {
      original = button.textContent;
      button.setAttribute("data-original-label", original);
    }
    button.textContent = label;
    window.setTimeout(function () {
      button.textContent = original;
    }, 1100);
  }

  function jumpToTurn(turnId) {
    var target = document.getElementById(turnId);
    if (!target) {
      return;
    }
    setActiveReferenceTurn(turnId);
    refreshReferencePanel(getAssistantRawForTurn(turnId));
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function scrollToTarget(targetId) {
    var target = document.getElementById(targetId);
    if (!target) {
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function getLastAssistantRaw() {
    var assistants = messages.querySelectorAll('.msg.assistant[data-raw]');
    if (!assistants.length) {
      return "";
    }
    return assistants[assistants.length - 1].getAttribute("data-raw") || "";
  }

  function setPromptAndFocus(text) {
    prompt.value = text;
    prompt.focus();
    if (typeof prompt.setSelectionRange === "function") {
      prompt.setSelectionRange(prompt.value.length, prompt.value.length);
    }
  }

  function handleChatSubmit(form, submittedText) {
    var userNode;
    var assistantNode;

    if (!submittedText.replace(/^\s+|\s+$/g, "")) {
      setStatusChrome("Please enter a prompt before sending.");
      prompt.focus();
      return;
    }

    setBusy(true, "...");
    setStatusChrome("Submitting prompt...");

    userNode = createUserMessageElement(submittedText);
    assistantNode = createAssistantPlaceholder();
    messages.appendChild(userNode);
    messages.appendChild(assistantNode);
    updateStarterVisibility();
    autoScrollLocked = false;
    shouldStickToBottom = true;
    scrollPageToBottom("auto", true);
    prompt.value = "";

    postForm(
      form,
      function (payload) {
        try {
          setStatusChrome("Writing response...");
          animateAssistantResponse(
            assistantNode,
            payload.assistant_text || "",
            payload.assistant_html || "",
            function () {
              if (typeof payload.session_id === "string") {
                updateSessionId(payload.session_id);
              }
              if (typeof payload.messages_html === "string") {
                updateMessages(payload.messages_html);
              }
              updatePromptHistory(payload.prompt_history_html);
              updateStarterHtml(payload.starter_html);
              setStatusChrome(payload.status || "Ready.");
            }
          );
        } catch (error) {
          if (assistantNode && assistantNode.parentNode) {
            assistantNode.parentNode.removeChild(assistantNode);
          }
          setStatusChrome("AJAX render failed; retrying with normal page submit.");
          if (form === composerForm) {
            submitClearedComposerFallback(submittedText);
            return;
          }
          form.submit();
        }
        finishSubmission();
      },
      function (reason) {
        if (assistantNode && assistantNode.parentNode) {
          assistantNode.parentNode.removeChild(assistantNode);
        }
        setStatusChrome("AJAX submit failed (" + reason + "); retrying with normal page submit.");
        if (form === composerForm) {
          submitClearedComposerFallback(submittedText);
          return;
        }
        rememberScrollRestore("bottom");
        form.submit();
        finishSubmission();
      }
    );
  }

  function handleComposerSubmit(event) {
    var submittedText = prompt.value || "";
    event.preventDefault();
    handleChatSubmit(composerForm, submittedText);
  }

  function postSimpleAction(actionPath, busyText) {
    var actionForm = document.createElement("form");
    var sessionInput = document.createElement("input");
    var variantInput = document.createElement("input");

    actionForm.action = actionPath;
    actionForm.method = "post";

    sessionInput.type = "hidden";
    sessionInput.name = "session_id";
    sessionInput.value = window.__MLPXPLORER__ ? (window.__MLPXPLORER__.sessionId || "") : "";
    variantInput.type = "hidden";
    variantInput.name = "ui_variant";
    variantInput.value = window.__MLPXPLORER__ ? (window.__MLPXPLORER__.uiVariant || "modern") : "modern";
    actionForm.appendChild(sessionInput);
    actionForm.appendChild(variantInput);
    document.body.appendChild(actionForm);

    setBusy(true, "...");
    setStatusChrome(busyText);

    postForm(
      actionForm,
      function (payload) {
        applyUiState(payload);
        finishSubmission();
      },
      function () {
        rememberScrollRestore("bottom");
        actionForm.submit();
        finishSubmission();
      }
    );
  }

  prompt.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (typeof composerForm.requestSubmit === "function") {
        composerForm.requestSubmit();
      } else {
        sendButton.click();
      }
    }
  });

  composerForm.addEventListener("submit", handleComposerSubmit);

  if (clearHistoryButton) {
    clearHistoryButton.addEventListener("click", function () {
      postSimpleAction("/clear-history", "Clearing question history...");
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    var messageInput;

    if (!form || form === composerForm || form.tagName !== "FORM") {
      return;
    }

    if (form.action.indexOf("/chat") !== -1) {
      event.preventDefault();
      messageInput = form.querySelector('input[name="message"]');
      handleChatSubmit(form, messageInput ? (messageInput.value || "") : "");
      return;
    }

    if (form.action.indexOf("/reset-chat") !== -1) {
      event.preventDefault();
      postSimpleAction("/reset-chat", "Starting a new chat...");
    }
  });

  document.addEventListener("click", function (event) {
    var actionButton = event.target.closest("[data-action]");
    var navButton = event.target.closest("[data-nav-target], [data-nav-action]");
    var turnNode = event.target.closest(".turn");
    var msg;
    var action;
    var raw;

    if (navButton) {
      if (navButton.hasAttribute("data-nav-target")) {
        scrollToTarget(navButton.getAttribute("data-nav-target"));
        return;
      }

      if (navButton.getAttribute("data-nav-action") === "datasets") {
        setPromptAndFocus("Compare the main datasets in the knowledge base by focus, size, methodology, and accessibility.");
        setStatusChrome("Added a dataset exploration prompt to the composer.");
        return;
      }

      if (navButton.getAttribute("data-nav-action") === "copy-last") {
        raw = getLastAssistantRaw();
        if (!raw) {
          setStatusChrome("There is no assistant response to save yet.");
          return;
        }
        try {
          copyText(raw);
          setStatusChrome("Copied the latest assistant response.");
        } catch (error) {
          setStatusChrome("Copy failed.");
        }
        return;
      }
    }

    if (!actionButton) {
      if (turnNode && turnNode.id) {
        setActiveReferenceTurn(turnNode.id);
        refreshReferencePanel(getAssistantRawForTurn(turnNode.id));
      }
      return;
    }

    action = actionButton.getAttribute("data-action");

    if (action === "jump-turn") {
      event.preventDefault();
      jumpToTurn(actionButton.getAttribute("data-target") || "");
      return;
    }

    msg = actionButton.closest(".msg");
    if (!msg) {
      return;
    }
    raw = msg.getAttribute("data-raw") || "";

    if (action === "copy") {
      try {
        copyText(raw);
        flashButtonLabel(actionButton, "Copied");
        setStatusChrome("Copied to clipboard.");
      } catch (error) {
        flashButtonLabel(actionButton, "Failed");
        setStatusChrome("Copy failed.");
      }
      return;
    }

    if (action === "edit") {
      prompt.value = raw;
      prompt.focus();
      setStatusChrome("Copied the prompt back into the composer.");
    }
  });

  if (toggleReferences && referenceList) {
    toggleReferences.addEventListener("click", function () {
      var panel = toggleReferences.closest(".reference-panel");
      var isOpen = toggleReferences.getAttribute("aria-expanded") !== "false";
      if (!panel) {
        return;
      }
      panel.classList.toggle("reference-hidden", isOpen);
      toggleReferences.setAttribute("aria-expanded", isOpen ? "false" : "true");
      toggleReferences.textContent = isOpen ? "v" : "^";
    });
  }

  messages.addEventListener("scroll", syncScrollIntent, { passive: true });
  messages.addEventListener("wheel", function () {
    autoScrollLocked = !isNearPageBottom();
    syncScrollIntent();
  }, { passive: true });
  messages.addEventListener("touchmove", function () {
    autoScrollLocked = !isNearPageBottom();
    syncScrollIntent();
  }, { passive: true });

  restoreScrollIfNeeded();
  cleanupAssistantReferenceBlocks();
  normalizeActionButtons(messages);
  setActiveReferenceTurn("");
  refreshReferencePanel();
  updateStarterVisibility();
  syncScrollIntent();
  setStatusChrome(status.textContent || "Ready.");
})();
