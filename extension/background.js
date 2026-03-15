chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "improve") {
    fetch("http://localhost:8555/improve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message.text, backend: message.backend })
    })
      .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        return response.json();
      })
      .then(data => sendResponse({ suggestions: data.suggestions }))
      .catch(err => sendResponse({ error: err.message }));

    return true;
  }

  if (message.action === "improve-block") {
    fetch("http://localhost:8555/improve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: message.text, backend: message.backend })
    })
      .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        return response.json();
      })
      .then(data => sendResponse({
        sessionId: message.sessionId,
        blockIndex: message.blockIndex,
        suggestion: data.suggestions[0]
      }))
      .catch(err => sendResponse({ error: err.message }));

    return true;
  }

  if (message.action === "improve-batch") {
    fetch("http://localhost:8555/improve-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sentences: message.sentences,
        backend: message.backend
      })
    })
      .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        return response.json();
      })
      .then(data => sendResponse({ results: data.results }))
      .catch(err => sendResponse({ error: err.message }));

    return true;
  }
});
