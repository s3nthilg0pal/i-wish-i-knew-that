const DEFAULT_API_URL = "https://api.senthil.nz/links";

const titleElement = document.querySelector("#page-title");
const urlElement = document.querySelector("#page-url");
const apiUrlInput = document.querySelector("#api-url");
const sendTitleInput = document.querySelector("#send-title");
const saveButton = document.querySelector("#save-link");
const statusElement = document.querySelector("#status");

let activeTab = null;

function setStatus(message, type = "") {
  statusElement.textContent = message;
  statusElement.className = `status ${type}`.trim();
}

function normalizeApiUrl(value) {
  const trimmed = value.trim().replace(/\/$/, "");
  if (!trimmed) {
    return DEFAULT_API_URL;
  }
  return trimmed.endsWith("/links") ? trimmed : `${trimmed}/links`;
}

async function loadSettings() {
  const settings = await chrome.storage.sync.get({
    apiUrl: DEFAULT_API_URL,
    sendTitle: false
  });
  apiUrlInput.value = settings.apiUrl;
  sendTitleInput.checked = settings.sendTitle;
}

async function saveSettings() {
  await chrome.storage.sync.set({
    apiUrl: normalizeApiUrl(apiUrlInput.value),
    sendTitle: sendTitleInput.checked
  });
}

async function loadActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tab;

  if (!tab?.url || !/^https?:\/\//.test(tab.url)) {
    titleElement.textContent = "This page cannot be saved";
    urlElement.textContent = tab?.url || "";
    saveButton.disabled = true;
    return;
  }

  titleElement.textContent = tab.title || tab.url;
  urlElement.textContent = tab.url;
  saveButton.disabled = false;
}

async function saveCurrentLink() {
  if (!activeTab?.url) {
    return;
  }

  saveButton.disabled = true;
  setStatus("Saving...");

  try {
    await saveSettings();

    const payload = { url: activeTab.url };
    if (sendTitleInput.checked && activeTab.title) {
      payload.title = activeTab.title;
    }

    const response = await fetch(normalizeApiUrl(apiUrlInput.value), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    });

    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.error || `Request failed with ${response.status}`);
    }

    setStatus(result.deploy_triggered ? "Saved. Deploy triggered." : "Saved.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    saveButton.disabled = false;
  }
}

apiUrlInput.addEventListener("change", saveSettings);
sendTitleInput.addEventListener("change", saveSettings);
saveButton.addEventListener("click", saveCurrentLink);

loadSettings()
  .then(loadActiveTab)
  .catch((error) => {
    saveButton.disabled = true;
    setStatus(error.message, "error");
  });
