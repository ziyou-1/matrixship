# coding: utf-8
import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import quote, urlparse

import xhs_note_replacement


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
VIDEO_JOB_RE = re.compile(r"^rvw_[0-9a-f]{24}$")
NOTE_JOB_RE = re.compile(r"^xnr_[0-9a-f]{24}$")
HANDOFF_RE = re.compile(r"^rwh_[0-9a-f]{24}$")
TASK_TYPES = {"video", "note"}
_NOTE_DATA_IMAGE_RE = re.compile(
    r"data:image(?:/[A-Za-z0-9.+-]+)?;base64(?:,[A-Za-z0-9+/=]+)?",
    re.IGNORECASE,
)
_NOTE_CREDENTIAL_RE = re.compile(
    r"\b(?:authorization\s*[:=]?\s*bearer|cookie|token|authorization|bearer)\b"
    "(?:\\s*[:=]\\s*|\\s+)?[^\\s,;\\uFF0C\\uFF1B\\u3002\\uFF01\\uFF1F]*",
    re.IGNORECASE,
)
_NOTE_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_NOTE_DATA_URL_RE = re.compile(
    r"data\s*:\s*[^,\s;]+(?:\s*;\s*[^,\s]+)*(?:\s*,\s*[^\s\"'<>)]*)?",
    re.IGNORECASE,
)
_NOTE_URL_RE = re.compile(r"\bhttps?://[^\s<>'\"]+", re.IGNORECASE)


def replacement_disabled_payload():
    return {"ok": False, "error": "replacement_web_disabled"}


def replacement_page_html():
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>\u66ff\u6362\u751f\u6210</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #1f2937; }
    main { max-width: 1120px; margin: 0 auto; padding: 24px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    .auth-line { display: flex; align-items: end; gap: 10px; margin: -6px 0 16px; max-width: 360px; }
    .auth-line label { margin: 0; min-width: 86px; }
    .auth-line input { max-width: 240px; }
    .auth-context { color: #667085; font-size: 13px; }
    h1 { font-size: 24px; margin: 0; letter-spacing: 0; }
    .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
    .tabs button { border: 1px solid #cfd6df; background: white; padding: 9px 14px; border-radius: 6px; cursor: pointer; }
    .tabs button.active { background: #183b56; color: white; border-color: #183b56; }
    section { background: white; border: 1px solid #dde3ea; border-radius: 8px; padding: 18px; }
    label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 6px; }
    input, textarea { width: 100%; box-sizing: border-box; border: 1px solid #cfd6df; border-radius: 6px; padding: 10px; font: inherit; }
    textarea { min-height: 88px; resize: vertical; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .actions { margin-top: 16px; display: flex; gap: 10px; align-items: center; }
    .primary { background: #16745f; color: white; border: 0; border-radius: 6px; padding: 10px 14px; cursor: pointer; }
    .primary:disabled { background: #9aa6b2; cursor: not-allowed; }
    .check-row { display: flex; align-items: flex-start; gap: 8px; font-weight: 500; margin: 8px 0 0; }
    .check-row input { width: auto; margin-top: 2px; }
    .auth-box { border: 1px solid #f0d9a8; background: #fffaf0; border-radius: 6px; padding: 10px 12px; margin-top: 8px; }
    .auth-hint { color: #9a6a00; font-size: 12px; margin-bottom: 4px; }
    .auth-box.disabled { opacity: .5; }
    .note-workspace { margin-top: 16px; display: grid; grid-template-columns: minmax(220px, .9fr) minmax(260px, 1fr) minmax(280px, 1fr); gap: 14px; align-items: start; }
    .tool-block { border: 1px solid #dde3ea; border-radius: 8px; padding: 12px; background: #fbfcfd; }
    .tool-block h2 { font-size: 15px; margin: 0 0 10px; letter-spacing: 0; }
    .slot-list, .copy-options { display: grid; gap: 8px; }
    .slot-item { border: 1px solid #d7dee7; border-radius: 6px; padding: 10px; background: white; min-height: 56px; }
    .slot-item img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 6px; border: 1px solid #e4e9f0; background: #eef2f6; margin-bottom: 8px; }
    .slot-item strong, .copy-option strong { display: block; font-size: 13px; margin-bottom: 4px; }
    .meta { color: #667085; font-size: 12px; overflow-wrap: anywhere; }
    .copy-option { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; border: 1px solid #d7dee7; border-radius: 6px; padding: 10px; background: white; cursor: pointer; }
    .copy-option:focus-within, .copy-option.selected { border-color: #16745f; box-shadow: 0 0 0 2px rgba(22,116,95,.12); }
    .copy-option input { width: 16px; height: 16px; margin-top: 2px; }
    .copy-body { color: #344054; font-size: 12px; line-height: 1.45; max-height: 86px; overflow: hidden; }
    .editor-panel textarea { min-height: 120px; }
    pre { background: #101820; color: #d8f3dc; border-radius: 6px; padding: 12px; overflow: auto; min-height: 90px; }
    [hidden] { display: none !important; }
    @media (max-width: 980px) { .note-workspace { grid-template-columns: 1fr; } }
    @media (max-width: 760px) { main { padding: 14px; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <header><h1>\u66ff\u6362\u751f\u6210</h1><span id="user-context" class="auth-context">\u672c\u5730\u6267\u884c\u7aef</span></header>
  <div class="auth-line"><label for="agent-token">Agent Token</label><input id="agent-token" type="password" autocomplete="current-password"></div>
  <div class="tabs">
    <button type="button" class="active" data-tab="video">\u89c6\u9891\u66ff\u6362</button>
    <button type="button" data-tab="note">\u56fe\u6587\u66ff\u6362</button>
  </div>
  <section id="video-panel">
    <div id="video-source-mode" class="auth-context">\u6765\u6e90\u6a21\u5f0f\uff1a\u76f4\u63a5\u94fe\u63a5</div>
    <form id="video-form">
      <label>\u6765\u6e90\u89c6\u9891\u94fe\u63a5</label><input name="sourceUrl" required aria-label="\u6765\u6e90\u89c6\u9891\u94fe\u63a5\u793a\u4f8b https://example.com/video">
      <div class="grid">
        <div><label>\u4eba\u7269\u56fe</label><input name="characterImage" type="file" accept="image/*" required></div>
        <div><label>\u4ea7\u54c1\u56fe</label><input name="productImage" type="file" accept="image/*"></div>
        <div><label>\u573a\u666f\u56fe</label><input name="sceneImage" type="file" accept="image/*"></div>
      </div>
      <label class="check-row"><input type="checkbox" name="noPersonMode" id="video-no-person"> \u7eaf\u4ea7\u54c1\u89c6\u9891\uff08\u65e0\u4eba\u7269\uff0c\u4e0d\u4e0a\u4f20\u4eba\u7269\u56fe\u3001\u4e0d\u505a\u6362\u8138\uff09</label>
      <div id="video-person-auth" class="auth-box">
        <div class="auth-hint">\u771f\u4eba\u8138\u56fe\u5fc5\u987b\u786e\u8ba4\u6388\u6743\uff1b\u4e0d\u652f\u6301\u672a\u6388\u6743\u771f\u4eba\u3001\u516c\u4f17\u4eba\u7269\u6216\u660e\u661f\u8138\u3002</div>
        <label class="check-row"><input type="checkbox" name="personFullBody" id="video-full-body"> \u8be5\u4eba\u7269\u56fe\u4e3a\u6e05\u6670\u6b63\u8138\u5168\u8eab\u7167\uff08\u5df2\u786e\u8ba4\uff09</label>
        <label class="check-row"><input type="checkbox" name="faceAuthorized" id="video-face-auth"> \u6211\u786e\u8ba4\u5df2\u83b7\u5f97\u8be5\u4eba\u7269\u7d20\u6750\u6388\u6743</label>
      </div>
      <label>\u53e3\u64ad\u7a3f</label><textarea name="script"></textarea>
      <label>\u5356\u70b9/\u98ce\u683c\u8981\u6c42</label><textarea name="sellingPoints"></textarea>
      <div class="grid">
        <div><label>\u540c\u6b3e\u66ff\u6362\u6a21\u578b</label><select name="model" id="video-model"><option value="">\u9ed8\u8ba4\u6a21\u578b</option></select></div>
        <div><label>\u58f0\u97f3</label><select name="audioMode" id="video-audio-mode"></select></div>
        <div id="video-voice-row" hidden><label>AI \u97f3\u8272</label><select name="voice" id="video-voice"></select></div>
      </div>
      <div class="actions"><button class="primary">\u51c6\u5907\u66ff\u6362\u4efb\u52a1</button></div>
    </form>
    <div id="video-plan" hidden>
      <h2 style="font-size:15px;margin:16px 0 8px;">\u955c\u5934\u8ba1\u5212</h2>
      <div id="video-segments" class="slot-list"></div>
      <div class="actions">
        <button class="primary" type="button" id="video-execute">\u5f00\u59cb\u751f\u6210</button>
        <button type="button" id="video-retry" class="primary" hidden>\u91cd\u8bd5\u5931\u8d25\u7247\u6bb5</button>
        <button type="button" id="video-cancel" hidden>\u53d6\u6d88\u4efb\u52a1</button>
        <button type="button" id="video-concat" class="primary" hidden>\u5408\u6210\u6210\u7247</button>
        <a id="video-download" href="#" hidden>\u4e0b\u8f7d\u6210\u7247</a>
      </div>
    </div>
    <pre id="video-status">{}</pre>
  </section>
  <section id="note-panel" hidden>
    <form id="note-form">
      <label>\u5c0f\u7ea2\u4e66\u56fe\u6587\u94fe\u63a5</label><input name="sourceUrl" required aria-label="\u5c0f\u7ea2\u4e66\u56fe\u6587\u94fe\u63a5\u793a\u4f8b https://www.xiaohongshu.com/explore/id">
      <label>\u66ff\u6362\u56fe\u7247</label><input name="replacementImages" type="file" accept="image/*" multiple required>
      <div class="grid">
        <div><label>\u4e1a\u52a1\u540d\u79f0</label><input name="businessName" required></div>
        <div><label>\u5730\u533a</label><input name="region"></div>
        <div><label>\u76ee\u6807\u5ba2\u6237</label><input name="audience"></div>
      </div>
      <label>\u5356\u70b9</label><textarea name="sellingPoints"></textarea>
      <label>\u8bed\u6c14</label><input name="tone">
      <div class="actions"><button class="primary">\u751f\u6210\u56fe\u6587\u66ff\u6362</button></div>
    </form>
    <pre id="note-status">{}</pre>
    <div id="note-preview" class="note-workspace" hidden>
      <div class="tool-block">
        <h2>\u56fe\u7247\u69fd\u4f4d</h2>
        <div id="note-slots" class="slot-list"></div>
      </div>
      <div class="tool-block">
        <h2>\u5019\u9009\u6587\u6848</h2>
        <div id="note-copy-options" class="copy-options"></div>
      </div>
      <div class="tool-block editor-panel">
        <h2>\u4fdd\u5b58\u6587\u6848</h2>
        <label for="note-title">\u6807\u9898</label><input id="note-title">
        <label for="note-body">\u6b63\u6587</label><textarea id="note-body"></textarea>
        <label for="note-tags">\u6807\u7b7e</label><input id="note-tags">
      </div>
    </div>
    <div class="actions"><button class="primary" type="button" id="note-save" disabled>\u4fdd\u5b58\u8349\u7a3f</button></div>
  </section>
</main>
<script>
const show = (id) => {
  document.querySelectorAll('.tabs button').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === id));
  document.getElementById('video-panel').hidden = id !== 'video';
  document.getElementById('note-panel').hidden = id !== 'note';
};
document.querySelectorAll('.tabs button').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.tab)));
const TOKEN_KEY = 'matrixReplacementAgentToken';
const USER_KEY = 'matrixReplacementUserContext';
const HANDOFF_KEY = 'matrixReplacementVideoHandoffId';
const JOB_KEY = 'matrixReplacementVideoJobId';
const VIDEO_PREP_POLL_MS = 1000;
const VIDEO_GEN_POLL_MS = 2000;
let videoPollTimer = null;
const tokenInput = document.getElementById('agent-token');
const hashParams = new URLSearchParams(location.hash.replace(/^#/, ''));
const hashToken = hashParams.get('token') || hashParams.get('agentToken') || '';
if (hashToken) {
  sessionStorage.setItem(TOKEN_KEY, hashToken);
}
const hashUser = hashParams.get('user') || '';
if (hashUser) sessionStorage.setItem(USER_KEY, hashUser);
const hashHandoff = hashParams.get('handoffId') || '';
if (hashHandoff) sessionStorage.setItem(HANDOFF_KEY, hashHandoff);
if (hashToken || hashUser || hashHandoff) history.replaceState(null, document.title, location.pathname);
tokenInput.value = sessionStorage.getItem(TOKEN_KEY) || '';
tokenInput.addEventListener('input', () => {
  const value = tokenInput.value.trim();
  if (value) sessionStorage.setItem(TOKEN_KEY, value);
  else sessionStorage.removeItem(TOKEN_KEY);
});
let currentNoteJobId = '';
let currentNoteJob = null;
function matrixReplacementUserContext() {
  const raw = sessionStorage.getItem(USER_KEY) || '';
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_error) {
    return {};
  }
}
function renderUserContext() {
  const user = matrixReplacementUserContext();
  const parts = [];
  if (user.displayName) parts.push(user.displayName);
  if (user.orgId) parts.push(user.orgId);
  document.getElementById('user-context').textContent = parts.length ? parts.join(' · ') : '\u672c\u5730\u6267\u884c\u7aef';
}
renderUserContext();
function currentVideoHandoffId() {
  return (sessionStorage.getItem(HANDOFF_KEY) || '').trim();
}
function authHeaders(extra = {}) {
  const headers = {...extra};
  const token = (tokenInput.value || sessionStorage.getItem(TOKEN_KEY) || '').trim();
  if (token) headers['X-Matrix-Agent-Token'] = token;
  return headers;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function copyTags(copy) {
  const tags = copy && Array.isArray(copy.tags) ? copy.tags : [];
  return tags.join(' ');
}
function populateCopyEditor(copy) {
  const selected = copy || {};
  document.getElementById('note-title').value = selected.title || '';
  document.getElementById('note-body').value = selected.body || '';
  document.getElementById('note-tags').value = copyTags(selected);
}
function collectCopyOverride() {
  return {
    title: document.getElementById('note-title').value.trim(),
    body: document.getElementById('note-body').value.trim(),
    tags: document.getElementById('note-tags').value.trim()
  };
}
function renderNoteSlots(job) {
  const slots = document.getElementById('note-slots');
  const mappings = Array.isArray(job.slotMappings) ? job.slotMappings : [];
  const images = Array.isArray(job.imageSlots) ? job.imageSlots : [];
  const files = Array.isArray(job.files) ? job.files : [];
  const count = Math.max(mappings.length, images.length, files.length);
  slots.innerHTML = '';
  for (let index = 0; index < count; index += 1) {
    const mapping = mappings[index] || {};
    const image = images[index] || {};
    const file = files[index] || {};
    const title = `#${escapeHtml(mapping.slotIndex || image.index || index + 1)} ${escapeHtml(mapping.slotRole || image.role || 'image')}`;
    const name = file.filename || image.sourceFile || '';
    const size = file.size ? `${file.size} bytes` : '';
    const imageHtml = file.previewUrl ? `<img data-preview-url="${escapeHtml(file.previewUrl)}" alt="${escapeHtml(name || title)}" loading="lazy" decoding="async">` : '';
    slots.insertAdjacentHTML('beforeend', `<div class="slot-item">${imageHtml}<strong>${title}</strong><div class="meta">${escapeHtml(name)}</div><div class="meta">${escapeHtml(size)}</div></div>`);
  }
}
async function loadSlotImages() {
  const images = Array.from(document.querySelectorAll('#note-slots img[data-preview-url]'));
  await Promise.all(images.map(async img => {
    const previewUrl = img.dataset.previewUrl || '';
    if (!previewUrl) return;
    try {
      const res = await fetch(previewUrl, {headers: authHeaders()});
      if (!res.ok) throw new Error(`preview ${res.status}`);
      const objectUrl = URL.createObjectURL(await res.blob());
      if (img.dataset.objectUrl) URL.revokeObjectURL(img.dataset.objectUrl);
      img.dataset.objectUrl = objectUrl;
      img.src = objectUrl;
    } catch (_error) {
      img.removeAttribute('src');
      img.title = 'preview_load_failed';
    }
  }));
}
function renderCopyOptions(job) {
  const holder = document.getElementById('note-copy-options');
  const candidates = Array.isArray(job.copyCandidates) ? job.copyCandidates : [];
  holder.innerHTML = '';
  candidates.forEach((copy, index) => {
    const checked = index === Number(job.selectedCopyIndex || 0) ? 'checked' : '';
    holder.insertAdjacentHTML('beforeend', `<label class="copy-option ${checked ? 'selected' : ''}"><input type="radio" name="note-copy-choice" value="${index}" ${checked}><span><strong>${escapeHtml(copy.title || '')}</strong><span class="copy-body">${escapeHtml(copy.body || '')}</span><span class="meta">${escapeHtml(copyTags(copy))}</span></span></label>`);
  });
  holder.querySelectorAll('input[name="note-copy-choice"]').forEach(input => {
    input.addEventListener('change', () => {
      holder.querySelectorAll('.copy-option').forEach(item => item.classList.remove('selected'));
      input.closest('.copy-option').classList.add('selected');
      populateCopyEditor(candidates[Number(input.value)] || {});
    });
  });
  populateCopyEditor(candidates[Number(job.selectedCopyIndex || 0)] || {});
}
function renderNotePreview(job) {
  currentNoteJob = job || {};
  document.getElementById('note-preview').hidden = false;
  renderNoteSlots(currentNoteJob);
  loadSlotImages();
  renderCopyOptions(currentNoteJob);
}
async function loadNoteJob(jobId) {
  const res = await fetch(`/api/replacement/note/job?jobId=${encodeURIComponent(jobId)}`, {headers: authHeaders()});
  return await res.json();
}
async function loadVideoHandoff() {
  const handoffId = currentVideoHandoffId();
  if (!handoffId || !authHeaders()['X-Matrix-Agent-Token']) return;
  const status = document.getElementById('video-status');
  try {
    const res = await fetch(`/api/replacement/video/handoff?handoffId=${encodeURIComponent(handoffId)}`, {headers: authHeaders()});
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      status.textContent = formatReplacementError(json, res.status) + '\\n\\n' + JSON.stringify(json, null, 2);
      return;
    }
    status.textContent = '\u5df2\u63a5\u5165\u672c\u5730\u5206\u89e3\u7ed3\u679c\uff0c\u53ef\u4e0a\u4f20\u66ff\u6362\u7d20\u6750\u540e\u521b\u5efa\u66ff\u6362\u4efb\u52a1\u3002\\n\\n' + JSON.stringify(json, null, 2);
    const sourceInput = document.querySelector('#video-form input[name="sourceUrl"]');
    if (sourceInput) sourceInput.required = false;
    const mode = document.getElementById('video-source-mode');
    if (mode) mode.textContent = '\u6765\u6e90\u6a21\u5f0f\uff1a\u672c\u5730\u5206\u89e3\u4ea4\u63a5 (' + handoffId + ')';
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  }
}
async function readJsonResponse(res) {
  const text = await res.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch (_error) {
    return {ok: false, error: 'replacement_response_invalid', message: text.slice(0, 200)};
  }
}
function formatReplacementError(payload, statusCode = 0) {
  const error = String((payload && (payload.error || payload.message)) || '');
  if (!authHeaders()['X-Matrix-Agent-Token']) return '\u8bf7\u4ece\u672c\u5730\u5ba2\u6237\u7aef\u6253\u5f00\u66ff\u6362\u7f51\u9875';
  if (error === 'agent_token_required' || statusCode === 401) return '\u6388\u6743\u5df2\u5931\u6548\uff0c\u8bf7\u56de\u5230\u5ba2\u6237\u7aef\u91cd\u65b0\u6253\u5f00';
  if (error === 'replacement_invalid_source_url') return '\u8bf7\u586b\u5199\u6709\u6548\u7684 http/https \u6765\u6e90\u94fe\u63a5';
  if (error === 'replacement_video_missing_character_image') return '\u8bf7\u4e0a\u4f20\u4eba\u7269\u53c2\u8003\u56fe';
  if (error === 'replacement_person_full_body_required') return '\u8bf7\u5148\u52fe\u9009\u786e\u8ba4\uff1a\u4e0a\u4f20\u7684\u4eba\u7269\u56fe\u662f\u6e05\u6670\u6b63\u8138\u5168\u8eab\u7167';
  if (error === 'replacement_face_authorization_required') return '\u8bf7\u5148\u52fe\u9009\u786e\u8ba4\uff1a\u5df2\u83b7\u5f97\u8be5\u4eba\u7269\u7d20\u6750\u6388\u6743\uff08\u4e0d\u652f\u6301\u672a\u6388\u6743\u771f\u4eba\u3001\u516c\u4f17\u4eba\u7269\u6216\u660e\u661f\u8138\uff09';
  if (error === 'replacement_note_missing_images') return '\u8bf7\u4e0a\u4f20\u81f3\u5c11\u4e00\u5f20\u66ff\u6362\u56fe\u7247';
  if (error === 'replacement_unsupported_file_type') return '\u8bf7\u4e0a\u4f20 PNG\u3001JPG\u3001JPEG \u6216 WEBP \u56fe\u7247';
  if (error === 'replacement_upload_too_large') return '\u56fe\u7247\u8fc7\u5927\uff0c\u8bf7\u538b\u7f29\u540e\u91cd\u8bd5';
  if (error === 'replacement_response_invalid') return '\u672c\u5730\u6267\u884c\u7aef\u8fd4\u56de\u5f02\u5e38\u54cd\u5e94\uff0c\u8bf7\u91cd\u542f\u5ba2\u6237\u7aef\u540e\u91cd\u8bd5';
  return error ? `\u66ff\u6362\u63d0\u4ea4\u5931\u8d25\uff1a${error}` : '\u66ff\u6362\u63d0\u4ea4\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5';
}
function formatReplacementSuccess(formId, payload) {
  return JSON.stringify(payload, null, 2);
}
async function submitForm(formId, url, statusId) {
  const form = document.getElementById(formId);
  const status = document.getElementById(statusId);
  const button = form.querySelector('button[type="submit"], button:not([type])');
  if (!authHeaders()['X-Matrix-Agent-Token']) {
    status.textContent = formatReplacementError({error: 'agent_token_required'}, 401);
    return;
  }
  status.textContent = '\u63d0\u4ea4\u4e2d...';
  if (button) button.disabled = true;
  try {
    const data = new FormData(form);
    if (formId === 'video-form' && currentVideoHandoffId()) data.set('handoffId', currentVideoHandoffId());
    const res = await fetch(url, {method: 'POST', body: data, headers: authHeaders()});
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      status.textContent = formatReplacementError(json, res.status) + '\\n\\n' + JSON.stringify(json, null, 2);
      return;
    }
    if (formId === 'note-form' && json.jobId) {
      currentNoteJobId = json.jobId;
      const jobJson = await loadNoteJob(json.jobId);
      if (jobJson.ok) renderNotePreview(jobJson);
      document.getElementById('note-save').disabled = false;
    }
    status.textContent = formatReplacementSuccess(formId, json);
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  } finally {
    if (button) button.disabled = false;
  }
}
async function saveNoteDraft() {
  const status = document.getElementById('note-status');
  if (!currentNoteJobId) return;
  if (!authHeaders()['X-Matrix-Agent-Token']) {
    status.textContent = formatReplacementError({error: 'agent_token_required'}, 401);
    return;
  }
  status.textContent = '\u4fdd\u5b58\u4e2d...';
  const button = document.getElementById('note-save');
  button.disabled = true;
  try {
    const selectedCopyIndex = Number(document.querySelector('input[name="note-copy-choice"]:checked')?.value || 0);
    const res = await fetch('/api/replacement/note/save-draft', {
      method: 'POST',
      headers: authHeaders({'Content-Type': 'application/json'}),
      body: JSON.stringify({jobId: currentNoteJobId, selectedCopyIndex, copyOverride: collectCopyOverride()})
    });
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      status.textContent = formatReplacementError(json, res.status) + '\\n\\n' + JSON.stringify(json, null, 2);
      return;
    }
    status.textContent = JSON.stringify(json, null, 2);
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  } finally {
    button.disabled = false;
  }
}
function currentVideoJobId() {
  return (sessionStorage.getItem(JOB_KEY) || '').trim();
}
function setVideoJobId(jobId) {
  if (jobId) sessionStorage.setItem(JOB_KEY, jobId);
  else sessionStorage.removeItem(JOB_KEY);
}
function videoStatusMessage(job) {
  const map = {
    planned: '镜头计划已生成，可编辑后点击开始生成。',
    running: '正在生成片段，请稍候…',
    awaiting_review: '片段已通过自动检查，请核对后合成成片。',
    partial: '有片段失败，可重试失败片段。',
    completed: '成片已合成，可下载。',
    done: '成片已合成，可下载。',
    failed: '任务失败，请检查来源或稍后重试。',
    cancelled: '任务已取消。',
    canceled: '任务已取消。'
  };
  return map[job && job.status] || (job && job.status) || '';
}
function videoHasFailedSegments(job) {
  return (job && Array.isArray(job.segments) ? job.segments : []).some(s => s && s.status === 'failed');
}
function renderVideoSegments(job) {
  const holder = document.getElementById('video-segments');
  const segments = job && Array.isArray(job.segments) ? job.segments : [];
  holder.innerHTML = '';
  segments.forEach(segment => {
    const title = '#' + escapeHtml(segment.index) + ' ' + escapeHtml(segment.status || 'planned');
    const range = escapeHtml((segment.start || 0) + 's - ' + (segment.end || 0) + 's');
    const note = escapeHtml(segment.stageLabel || segment.stage || '');
    const err = segment.error ? '<div class="meta">' + escapeHtml(segment.error) + '</div>' : '';
    holder.insertAdjacentHTML('beforeend',
      '<div class="slot-item"><strong>' + title + '</strong>' +
      '<div class="meta">' + range + '</div>' +
      '<div class="meta">' + note + '</div>' + err +
      '<input data-segment-index="' + escapeHtml(segment.index) + '" placeholder="可补充本段要求"></div>');
  });
}
function collectVideoPlanOverrides() {
  const inputs = Array.from(document.querySelectorAll('#video-segments input[data-segment-index]'));
  const segments = inputs
    .map(input => ({index: Number(input.dataset.segmentIndex), note: (input.value || '').trim()}))
    .filter(item => item.note);
  return segments.length ? {segments} : {};
}
function renderVideoJob(job) {
  const plan = document.getElementById('video-plan');
  const status = document.getElementById('video-status');
  if (!job || !job.jobId) { plan.hidden = true; return; }
  plan.hidden = false;
  renderVideoSegments(job);
  const failed = videoHasFailedSegments(job);
  const running = job.status === 'running';
  document.getElementById('video-execute').hidden = !(job.status === 'planned');
  document.getElementById('video-retry').hidden = !(job.status === 'partial' && failed);
  document.getElementById('video-cancel').hidden = !(job.status === 'planned' || running);
  document.getElementById('video-concat').hidden = !(job.status === 'awaiting_review');
  const download = document.getElementById('video-download');
  const canDownload = !!(job.download && job.download.available);
  download.hidden = !canDownload;
  download.dataset.filename = canDownload ? (job.download.filename || '') : '';
  status.textContent = videoStatusMessage(job) + '\\n\\n' + JSON.stringify(job, null, 2);
}
async function pollVideoJob() {
  const jobId = currentVideoJobId();
  if (!jobId || !authHeaders()['X-Matrix-Agent-Token']) return;
  if (videoPollTimer) { clearTimeout(videoPollTimer); videoPollTimer = null; }
  try {
    const res = await fetch('/api/replacement/video/job?jobId=' + encodeURIComponent(jobId), {headers: authHeaders()});
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      document.getElementById('video-status').textContent = formatReplacementError(json, res.status);
      return;
    }
    renderVideoJob(json);
    const active = json.status === 'planned' || json.status === 'running';
    if (active) {
      const delay = json.status === 'running' ? VIDEO_GEN_POLL_MS : VIDEO_PREP_POLL_MS;
      videoPollTimer = setTimeout(pollVideoJob, delay);
    }
  } catch (error) {
    document.getElementById('video-status').textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  }
}
async function prepareVideoJob() {
  const form = document.getElementById('video-form');
  const status = document.getElementById('video-status');
  const button = form.querySelector('button[type="submit"], button:not([type])');
  if (!authHeaders()['X-Matrix-Agent-Token']) {
    status.textContent = formatReplacementError({error: 'agent_token_required'}, 401);
    return;
  }
  status.textContent = '准备中...';
  if (button) button.disabled = true;
  try {
    const data = new FormData(form);
    if (currentVideoHandoffId()) data.set('handoffId', currentVideoHandoffId());
    const res = await fetch('/api/replacement/video/prepare', {method: 'POST', body: data, headers: authHeaders()});
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      status.textContent = formatReplacementError(json, res.status) + '\\n\\n' + JSON.stringify(json, null, 2);
      return;
    }
    setVideoJobId(json.jobId);
    status.textContent = '本地视频替换任务已创建。\\n\\n' + JSON.stringify(json, null, 2);
    renderVideoJob(json);
    pollVideoJob();
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  } finally {
    if (button) button.disabled = false;
  }
}
async function videoLifecycleCall(url, payload, activeMessage) {
  const jobId = currentVideoJobId();
  const status = document.getElementById('video-status');
  if (!jobId) return;
  if (!authHeaders()['X-Matrix-Agent-Token']) {
    status.textContent = formatReplacementError({error: 'agent_token_required'}, 401);
    return;
  }
  status.textContent = activeMessage || '处理中...';
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: authHeaders({'Content-Type': 'application/json'}),
      body: JSON.stringify(Object.assign({jobId}, payload || {}))
    });
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) {
      status.textContent = formatReplacementError(json, res.status) + '\\n\\n' + JSON.stringify(json, null, 2);
      return;
    }
    renderVideoJob(json);
    pollVideoJob();
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  }
}
function executeVideoJob() {
  videoLifecycleCall('/api/replacement/video/execute', {overrides: collectVideoPlanOverrides()}, '已提交生成...');
}
function retryVideoFailed() {
  videoLifecycleCall('/api/replacement/video/retry', {}, '重试失败片段...');
}
function cancelVideoJob() {
  videoLifecycleCall('/api/replacement/video/cancel', {}, '取消中...');
}
function concatVideoJob() {
  videoLifecycleCall('/api/replacement/video/concat', {}, '合成成片...');
}
async function downloadVideoResult(event) {
  if (event) event.preventDefault();
  const jobId = currentVideoJobId();
  const filename = (document.getElementById('video-download').dataset.filename || '').trim();
  if (!jobId || !filename) return;
  const status = document.getElementById('video-status');
  try {
    const url = '/api/replacement/video/download?jobId=' + encodeURIComponent(jobId) + '&filename=' + encodeURIComponent(filename);
    const res = await fetch(url, {headers: authHeaders()});
    if (!res.ok) { status.textContent = formatReplacementError({error: 'replacement_download_failed'}, res.status); return; }
    const objectUrl = URL.createObjectURL(await res.blob());
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (error) {
    status.textContent = formatReplacementError({error: error && error.message ? error.message : 'network_error'});
  }
}
function syncVideoPersonMode() {
  const noPerson = document.getElementById('video-no-person');
  const authBox = document.getElementById('video-person-auth');
  const character = document.querySelector('#video-form input[name="characterImage"]');
  const off = !!(noPerson && noPerson.checked);
  if (authBox) { authBox.classList.toggle('disabled', off); authBox.style.display = off ? 'none' : ''; }
  if (character) character.required = !off;
}
function syncVideoAudioMode() {
  const mode = document.getElementById('video-audio-mode');
  const row = document.getElementById('video-voice-row');
  if (row) row.hidden = !(mode && mode.value === 'tts');
}
async function loadVideoOptions() {
  try {
    const res = await fetch('/api/replacement/video/options', {headers: authHeaders()});
    const json = await readJsonResponse(res);
    if (!res.ok || !json.ok) return;
    const fill = (id, items, keepFirst) => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const start = keepFirst && sel.options.length ? 1 : 0;
      while (sel.options.length > start) sel.remove(start);
      (items || []).forEach(it => {
        const opt = document.createElement('option');
        opt.value = it.value; opt.textContent = it.label;
        sel.appendChild(opt);
      });
    };
    fill('video-model', json.models, true);
    fill('video-audio-mode', json.audioModes, false);
    fill('video-voice', json.voices, false);
    syncVideoAudioMode();
  } catch (_e) {}
}
document.getElementById('video-audio-mode').addEventListener('change', syncVideoAudioMode);
document.getElementById('video-no-person').addEventListener('change', syncVideoPersonMode);
document.getElementById('video-form').addEventListener('submit', e => { e.preventDefault(); prepareVideoJob(); });
document.getElementById('video-execute').addEventListener('click', executeVideoJob);
document.getElementById('video-retry').addEventListener('click', retryVideoFailed);
document.getElementById('video-cancel').addEventListener('click', cancelVideoJob);
document.getElementById('video-concat').addEventListener('click', concatVideoJob);
document.getElementById('video-download').addEventListener('click', downloadVideoResult);
document.getElementById('note-form').addEventListener('submit', e => { e.preventDefault(); submitForm('note-form', '/api/replacement/note/start', 'note-status'); });
document.getElementById('note-save').addEventListener('click', saveNoteDraft);
syncVideoPersonMode();
loadVideoOptions();
loadVideoHandoff();
if (currentVideoJobId()) pollVideoJob();
</script>
</body>
</html>"""

def _job_root(data_dir):
    return os.path.join(data_dir, "replacement_web_jobs")


def _handoff_root(data_dir):
    return os.path.join(data_dir, "replacement_web_handoffs")


def _task_root(data_dir, task_type):
    if task_type not in TASK_TYPES:
        raise ValueError("invalid_task_type")
    return os.path.join(_job_root(data_dir), task_type)


def _upload_root(data_dir, task_type, job_id):
    return os.path.join(data_dir, "replacement_web_uploads", task_type, job_id)


def preview_url(task_type, job_id, filename):
    return (
        "/api/replacement/file?taskType=%s&jobId=%s&filename=%s"
        % (quote(str(task_type or ""), safe=""), quote(str(job_id or ""), safe=""), quote(str(filename or ""), safe=""))
    )


def _new_video_job_id():
    return "rvw_" + uuid.uuid4().hex[:24]


def _new_video_handoff_id():
    return "rwh_" + uuid.uuid4().hex[:24]


def _valid_job_id(task_type, job_id):
    job_id = str(job_id or "").strip()
    if task_type == "video":
        return bool(VIDEO_JOB_RE.match(job_id))
    if task_type == "note":
        return bool(NOTE_JOB_RE.match(job_id))
    return False


def _valid_handoff_id(handoff_id):
    return bool(HANDOFF_RE.match(str(handoff_id or "").strip()))


def _safe_url_parts(value):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    path_hash = hashlib.sha256(parsed.path.encode("utf-8")).hexdigest()[:12]
    host = parsed.hostname or ""
    if parsed.port:
        host = "%s:%s" % (host, parsed.port)
    return {"scheme": parsed.scheme, "host": host, "pathHash": path_hash}


def _error(error, stage="preflight", status=400):
    return {"ok": False, "error": error, "stage": stage, "statusCode": status}


def _image_files(files, field_names):
    names = set(field_names)
    return [(field, filename, data) for field, filename, data in files or [] if field in names]


def _safe_filename(filename):
    safe = os.path.basename(str(filename or "")).replace("\\", "_").replace("/", "_")
    return _sanitize_note_text(safe)


def _redact_note_url(match):
    raw = match.group(0)
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "[redacted-url]"
    host = parsed.hostname or ""
    if parsed.port:
        host = "%s:%s" % (host, parsed.port)
    return "%s://%s/[redacted-url]" % (parsed.scheme, host)


def _sanitize_note_text(value):
    text = str(value or "")
    text = _NOTE_DATA_URL_RE.sub("[redacted]", text)
    text = _NOTE_URL_RE.sub(_redact_note_url, text)
    text = _NOTE_CREDENTIAL_RE.sub("[redacted]", text)
    text = _NOTE_BASE64_RE.sub("[redacted]", text)
    text = re.sub(r"(?i)data\s*:\s*[^,\s;]+(?:\s*;\s*base64)?", "[redacted]", text)
    return re.sub(r"(?i)\b(cookie|token|authorization|bearer)\b", "[redacted]", text)


def _sanitize_note_value(value):
    if isinstance(value, dict):
        return {key: _sanitize_note_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_note_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_note_text(value)
    return value


def _validate_images(files):
    for _field, filename, data in files:
        ext = os.path.splitext(str(filename or "").lower())[1]
        if ext not in IMAGE_EXTENSIONS:
            return _error("replacement_unsupported_file_type")
        if len(data or b"") > MAX_IMAGE_BYTES:
            return _error("replacement_upload_too_large")
    return None


def _file_metadata(files):
    return [
        {
            "field": str(field or ""),
            "filename": _safe_filename(filename),
            "size": len(data or b""),
        }
        for field, filename, data in files or []
    ]


def _write_upload_files(data_dir, task_type, job_id, files):
    root = _upload_root(data_dir, task_type, job_id)
    os.makedirs(root, exist_ok=True)
    saved = []
    used = set()
    for index, (field, filename, data) in enumerate(files or [], start=1):
        safe = _safe_filename(filename) or ("image_%02d.png" % index)
        name = "%02d_%s" % (index, safe)
        while name in used:
            name = "%02d_%s_%d" % (index, safe, len(used) + 1)
        used.add(name)
        path = os.path.join(root, name)
        with open(path, "wb") as f:
            f.write(data or b"")
        saved.append((field, name, path, len(data or b"")))
    return saved


def upload_file_path(data_dir, task_type, job_id, filename):
    if task_type not in TASK_TYPES or not _valid_job_id(task_type, job_id):
        return None, "bad_path", 400
    name = str(filename or "").strip()
    if not name or name != os.path.basename(name.replace("\\", "/")):
        return None, "bad_path", 400
    ext = os.path.splitext(name.lower())[1]
    if ext not in IMAGE_EXTENSIONS:
        return None, "unsupported_file_type", 400
    root = os.path.abspath(_upload_root(data_dir, task_type, job_id))
    path = os.path.abspath(os.path.normpath(os.path.join(root, name)))
    if path != root and not path.startswith(root + os.sep):
        return None, "forbidden", 403
    if not os.path.isfile(path):
        return None, "not_found", 404
    return path, "", 200


def _write_job(data_dir, task_type, job):
    root = os.path.join(_task_root(data_dir, task_type), job["id"])
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "job.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def create_video_handoff(data_dir, source, user=None, ttl_sec=3600):
    source = source if isinstance(source, dict) else {}
    url_parts = _safe_url_parts(source.get("sourceUrl"))
    if not url_parts:
        return _error("replacement_invalid_source_url")
    handoff_id = _new_video_handoff_id()
    now = time.time()
    try:
        ttl = max(60, int(ttl_sec))
    except (TypeError, ValueError):
        ttl = 3600
    source_video_path = str(source.get("sourceVideoPath") or "").strip()
    analysis = _sanitize_note_value(source.get("breakdownAnalysis") or {})
    handoff = {
        "id": handoff_id,
        "taskType": "video",
        "source": url_parts,
        "sourceUrl": "%s://%s/[redacted-url]" % (url_parts.get("scheme") or "https", url_parts.get("host") or ""),
        "sourceVideoPath": source_video_path,
        "platform": _sanitize_note_text(source.get("platform") or ""),
        "breakdownAnalysis": analysis if isinstance(analysis, dict) else {},
        "user": _sanitize_note_value(user or {}),
        "createdAt": now,
        "expiresAt": now + ttl,
    }
    root = _handoff_root(data_dir)
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, handoff_id + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(handoff, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return {"ok": True, "handoffId": handoff_id, "expiresAt": handoff["expiresAt"]}


def load_video_handoff(data_dir, handoff_id):
    handoff_id = str(handoff_id or "").strip()
    if not _valid_handoff_id(handoff_id):
        return None
    path = os.path.join(_handoff_root(data_dir), handoff_id + ".json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return None
    try:
        if float(data.get("expiresAt") or 0) < time.time():
            return None
    except (TypeError, ValueError):
        return None
    return data


def _handoff_analysis_summary(handoff):
    analysis = handoff.get("breakdownAnalysis") if isinstance(handoff.get("breakdownAnalysis"), dict) else {}
    meta = analysis.get("meta") if isinstance(analysis.get("meta"), dict) else {}
    transcript = analysis.get("transcript") if isinstance(analysis.get("transcript"), dict) else {}
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    try:
        duration = float(meta.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "transcriptSegmentCount": len(segments),
        "hasBreakdownAnalysis": bool(analysis),
    }


def _handoff_source_context(handoff):
    source_path = str(handoff.get("sourceVideoPath") or "")
    summary = _handoff_analysis_summary(handoff)
    return {
        "handoffId": str(handoff.get("id") or ""),
        "platform": _sanitize_note_text(handoff.get("platform") or ""),
        "duration": summary.get("duration") or 0,
        "hasBreakdownAnalysis": bool(summary.get("hasBreakdownAnalysis")),
        "sourceVideoAvailable": bool(source_path and os.path.isfile(source_path)),
        "sourceVideoPathHash": hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:12] if source_path else "",
    }


def handoff_response(handoff):
    handoff = handoff or {}
    source_path = str(handoff.get("sourceVideoPath") or "")
    return {
        "ok": True,
        "handoffId": str(handoff.get("id") or ""),
        "source": _sanitize_note_value(handoff.get("source") or {}),
        "sourceVideo": {
            "available": bool(source_path and os.path.isfile(source_path)),
            "pathHash": hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:12] if source_path else "",
        },
        "platform": _sanitize_note_text(handoff.get("platform") or ""),
        "analysis": _handoff_analysis_summary(handoff),
        "user": _sanitize_note_value(handoff.get("user") or {}),
        "createdAt": handoff.get("createdAt") or 0,
        "expiresAt": handoff.get("expiresAt") or 0,
    }


def load_job(data_dir, task_type, job_id):
    if not _valid_job_id(task_type, job_id):
        return None
    path = os.path.join(_task_root(data_dir, task_type), job_id, "job.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def _response_files(job):
    files = []
    for item in job.get("files") or []:
        if isinstance(item, dict):
            files.append({
                "field": _sanitize_note_text(item.get("field") or ""),
                "filename": _sanitize_note_text(item.get("filename") or ""),
                "size": item.get("size") or 0,
                "previewFilename": _sanitize_note_text(item.get("previewFilename") or item.get("storedFilename") or ""),
            })
    if job.get("taskType") != "note":
        for item in files:
            item.pop("previewFilename", None)
        return files
    job_id = job.get("id") or ""
    for item in files:
        preview_name = item.get("previewFilename") or item.get("storedFilename") or ""
        if preview_name:
            item["previewUrl"] = preview_url("note", job_id, preview_name)
            item.pop("previewFilename", None)
            item.pop("storedFilename", None)
    return files


def _response_slot_mappings(job):
    result = []
    for mapping in job.get("slotMappings") or []:
        if not isinstance(mapping, dict):
            continue
        item = {
            "slotIndex": mapping.get("slotIndex"),
            "slotRole": _sanitize_note_text(mapping.get("slotRole") or ""),
            "source": _sanitize_note_text(mapping.get("source") or ""),
            "assetId": _sanitize_note_text(mapping.get("assetId") or ""),
            "confirmationStatus": _sanitize_note_text(mapping.get("confirmationStatus") or ""),
            "hasFile": bool(mapping.get("filePath")),
        }
        result.append(item)
    return result


def job_response(job):
    job = job or {}
    result = {
        "ok": True,
        "jobId": job.get("id") or "",
        "taskType": job.get("taskType") or "",
        "status": job.get("status") or "",
        "stage": job.get("stage") or "",
        "progressText": job.get("progressText") or "",
        "source": _sanitize_note_value(job.get("source") or {}),
        "files": _response_files(job),
        "createdAt": job.get("createdAt") or 0,
        "updatedAt": job.get("updatedAt") or 0,
        "result": job.get("result") or {},
        "error": job.get("error") or "",
    }
    if job.get("taskType") == "note":
        result["imageSlots"] = _sanitize_note_value(job.get("imageSlots") or [])
        result["slotMappings"] = _response_slot_mappings(job)
        result["copyCandidates"] = _sanitize_note_value(job.get("copyCandidates") or [])
        result["draftMaterialId"] = str(job.get("draftMaterialId") or "")
    if job.get("taskType") == "video":
        result["sourceContext"] = _sanitize_note_value(job.get("sourceContext") or {})
    return result


def mark_note_draft_saved(data_dir, job_id, draft_material_id, xhs_job=None, material=None):
    job = load_job(data_dir, "note", job_id)
    if not job:
        return None
    job["status"] = "draft"
    job["stage"] = "draft_saved"
    job["draftMaterialId"] = str(draft_material_id or "")
    job["updatedAt"] = time.time()
    if xhs_job:
        job["xhsJobId"] = _sanitize_note_text(xhs_job.get("id") or job_id)
        job["imageSlots"] = _sanitize_note_value((xhs_job.get("template") or {}).get("imageSlots") or job.get("imageSlots") or [])
        job["slotMappings"] = _sanitize_note_value(xhs_job.get("slotMappings") or [])
        job["copyCandidates"] = _sanitize_note_value(xhs_job.get("copyCandidates") or [])
    if material:
        job["result"] = {
            "draftMaterialId": str(draft_material_id or ""),
            "materialType": _sanitize_note_text(material.get("type") or ""),
            "fileCount": len(material.get("files") or []),
        }
    _write_job(data_dir, "note", job)
    return job


def start_video_job(data_dir, fields, files):
    fields = fields or {}
    handoff_id = str(fields.get("handoffId") or "").strip()
    handoff = load_video_handoff(data_dir, handoff_id) if handoff_id else None
    if handoff_id and not handoff:
        return _error("replacement_video_handoff_not_found")
    url_parts = (handoff.get("source") if handoff else None) or _safe_url_parts(fields.get("sourceUrl"))
    if not url_parts:
        return _error("replacement_invalid_source_url")
    images = _image_files(files, {"characterImage", "productImage", "sceneImage"})
    validation_error = _validate_images(images)
    if validation_error:
        return validation_error
    gate_error = _video_person_gate(fields, images)
    if gate_error:
        return gate_error
    job_id = _new_video_job_id()
    now = time.time()
    files_metadata = _file_metadata(images)
    job = {
        "id": job_id,
        "taskType": "video",
        "status": "queued",
        "stage": "created",
        "progressText": "Phase 0 skeleton job created",
        "source": url_parts,
        "handoffId": handoff_id if handoff else "",
        "sourceContext": _handoff_source_context(handoff) if handoff else {},
        "files": files_metadata,
        "assetCount": len(files_metadata),
        "inputs": {
            "hasScript": bool(str((fields or {}).get("script") or "").strip()),
            "hasSellingPoints": bool(str((fields or {}).get("sellingPoints") or "").strip()),
        },
        "result": {"videoUrl": "", "localPath": ""},
        "createdAt": now,
        "updatedAt": now,
    }
    _write_job(data_dir, "video", job)
    return {"ok": True, "jobId": job_id, "taskType": "video", "status": "queued", "stage": "created"}


def _video_service_data_dir(data_dir):
    return _task_root(data_dir, "video")


def _platform_from_source_url(url):
    host = (urlparse(str(url or "").strip()).hostname or "").lower()
    if "xiaohongshu" in host or "xhslink" in host:
        return "xhs"
    if "douyin" in host or "iesdouyin" in host:
        return "douyin"
    return ""


class _SourceDownloader:
    """Direct-URL source downloader backed by the native client helpers.

    The handoff path never invokes this; direct-URL prepare depends on a
    native download entry point that is wired by the shared-service adapter.
    """

    def __init__(self, helpers):
        self._helpers = helpers

    def download(self, source_url, job_dir):
        for name in (
                "_replacement_web_download_source",
                "_download_reference_video",
                "download_source_video"):
            fn = getattr(self._helpers, name, None)
            if callable(fn):
                return fn(source_url, job_dir)
        raise RuntimeError("replacement_source_download_unavailable")


def _build_pipeline():
    try:
        import matrix_native_client as helpers
    except Exception:
        import replacement_pipeline
        return replacement_pipeline.ReplacementPipeline()
    # Route hybrid vs comic_project per job mode (matches the native Qt page and
    # the product default VIDEO_REPLACE_DEFAULT_MODE), instead of always hybrid.
    return helpers._replacement_service_pipeline()


def _build_source_resolver():
    import replacement_service
    import replacement_analysis
    try:
        import matrix_native_client as helpers
    except Exception:
        helpers = None
    if helpers is None:
        # Degraded resolver: handoff reuse still works; direct-URL is unavailable
        # until the shared-service adapter provides native download helpers.
        return replacement_service.SourceResolver(replacement_analysis.ReplacementAnalysis())

    def transcription_runner(source_path, out_dir, progress=None):
        return helpers._transcribe_breakdown_audio(source_path, out_dir=out_dir, progress=None)

    analysis = replacement_analysis.ReplacementAnalysis(
        downloader=_SourceDownloader(helpers),
        download_validator=helpers._breakdown_source_validation,
        platform_from_url=_platform_from_source_url,
        source_validator=helpers._breakdown_source_validation,
        frame_extractor=helpers._extract_breakdown_frames,
        ocr_runner=helpers._ocr_breakdown_frames,
        transcription_runner=transcription_runner,
        vision_runner=helpers.lk888_vision,
        report_builder=helpers._generate_video_breakdown_report,
        markdown_builder=helpers._video_breakdown_markdown,
        image_data_url=helpers._image_data_url,
        json_logger=lambda event, **fields: helpers.json_log(helpers._CLIENT_JSON_LOGGER, event, **fields),
        log_event=lambda *args, **kwargs: None,
    )
    return replacement_service.SourceResolver(analysis)


def build_video_service(data_dir):
    """Construct the ReplacementService the web layer orchestrates.

    Jobs persist under the same video task root that ``load_job`` reads, so
    ``job.json`` stays the single cross-process source of truth. Tests patch
    this factory to inject fake source resolver + pipeline (fake-provider).
    """
    import replacement_service
    logger = None
    try:
        import matrix_native_client as helpers
        logger = getattr(helpers, "_CLIENT_JSON_LOGGER", None)
    except Exception:
        logger = None
    return replacement_service.ReplacementService(
        data_dir=_video_service_data_dir(data_dir),
        source_resolver=_build_source_resolver(),
        pipeline=_build_pipeline(),
        # Terminal metrics + the Qt new-job circuit breaker share the agent data
        # root so the shared-service failure ratio is consistent across surfaces.
        metrics_dir=data_dir,
        logger=logger,
    )


def _truthy_field(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "checked")


def _video_person_gate(fields, images):
    """Real-person compliance gate, mirroring the native VideoReplacementPage.

    A real face reference may only be used after the user confirms (a) it is a
    clear full-body front photo and (b) they hold the authorization for it. This
    blocks unauthorized real people, public figures and celebrity faces exactly
    like the Qt page. Product-only jobs (纯产品视频 / no-person mode) skip the face
    requirements entirely.
    """
    fields = fields or {}
    has_character = any(field == "characterImage" for field, _f, _d in (images or []))
    if _truthy_field(fields.get("noPersonMode")):
        return None
    if not has_character:
        return _error("replacement_video_missing_character_image")
    if not _truthy_field(fields.get("personFullBody")):
        return _error("replacement_person_full_body_required")
    if not _truthy_field(fields.get("faceAuthorized")):
        return _error("replacement_face_authorization_required")
    return None


_WEB_AUDIO_MODES = (
    {"value": "auto", "label": "自动（生成视频自带声音）"},
    {"value": "tts", "label": "AI 音色配音"},
)


def video_replacement_options():
    """Model / audio-mode / voice choices for the web video replacement form.

    Models and voices come from the same native catalog the Qt page uses, so the
    web and desktop offer identical choices. Falls back to empty lists when the
    native helpers are unavailable (e.g. isolated tests); the pipeline then uses
    its defaults.
    """
    models, voices = [], []
    try:
        import matrix_native_client as helpers
    except Exception:
        helpers = None
    if helpers is not None:
        try:
            for row in (helpers._replacement_supported_model_rows() or []):
                name = str((row or {}).get("name") or "").strip()
                if name:
                    models.append({"value": name, "label": str((row or {}).get("display_name") or name)})
        except Exception:
            models = []
        try:
            for label, voice_id in (getattr(helpers, "DH_VOICES", None) or []):
                vid = str(voice_id or "").strip()
                if vid:
                    voices.append({"value": vid, "label": str(label or vid)})
        except Exception:
            voices = []
    return {"models": models, "voices": voices, "audioModes": [dict(m) for m in _WEB_AUDIO_MODES]}


def _allowed_video_model_names():
    return {m["value"] for m in video_replacement_options()["models"]}


def _allowed_voice_ids():
    return {v["value"] for v in video_replacement_options()["voices"]}


def _video_prepare_request(fields, handoff):
    fields = fields or {}
    request = {}
    source_url = str(fields.get("sourceUrl") or "").strip()
    if source_url:
        request["sourceUrl"] = source_url
    if handoff:
        request["handoff"] = handoff
        request["handoffId"] = str(handoff.get("id") or "").strip()
    request["noPersonMode"] = _truthy_field(fields.get("noPersonMode"))
    request["faceAuthorized"] = _truthy_field(fields.get("faceAuthorized"))
    request["personFullBody"] = _truthy_field(fields.get("personFullBody"))
    model = str(fields.get("model") or "").strip()
    if model and model in _allowed_video_model_names():
        request["model"] = model
    audio_mode = str(fields.get("audioMode") or "").strip().lower()
    if audio_mode in ("auto", "tts"):
        request["audioMode"] = audio_mode
    voice = str(fields.get("voice") or "").strip()
    if voice and voice in _allowed_voice_ids():
        request["voice"] = voice
    request["inputs"] = {
        "hasScript": bool(str(fields.get("script") or "").strip()),
        "hasSellingPoints": bool(str(fields.get("sellingPoints") or "").strip()),
        "script": _sanitize_note_text(fields.get("script") or ""),
        "sellingPoints": _sanitize_note_text(fields.get("sellingPoints") or ""),
    }
    return request


def _normalize_segment_indices(segment_indices):
    values = []
    for item in segment_indices or []:
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return values


def prepare_video_job(data_dir, fields, files):
    fields = fields or {}
    handoff_id = str(fields.get("handoffId") or "").strip()
    handoff = load_video_handoff(data_dir, handoff_id) if handoff_id else None
    if handoff_id and not handoff:
        return _error("replacement_video_handoff_not_found")
    if not handoff and not _safe_url_parts(fields.get("sourceUrl")):
        return _error("replacement_invalid_source_url")
    images = _image_files(files, {"characterImage", "productImage", "sceneImage"})
    validation_error = _validate_images(images)
    if validation_error:
        return validation_error
    gate_error = _video_person_gate(fields, images)
    if gate_error:
        return gate_error
    job_id = _new_video_job_id()
    _write_upload_files(data_dir, "video", job_id, images)
    request = _video_prepare_request(fields, handoff)
    service = build_video_service(data_dir)
    try:
        service.prepare(job_id, request, [(field, filename, data) for field, filename, data in images])
    except ValueError as exc:
        return _error(str(exc) or "replacement_prepare_failed", stage="prepare", status=400)
    except Exception:
        return _error("replacement_prepare_failed", stage="prepare", status=500)
    raw = load_job(data_dir, "video", job_id)
    if not raw:
        return _error("replacement_job_not_found", stage="prepare", status=500)
    return video_job_response(raw)


def execute_video_job(data_dir, job_id, overrides):
    if not _valid_job_id("video", job_id) or not load_job(data_dir, "video", job_id):
        return _error("replacement_job_not_found", stage="execute", status=404)
    service = build_video_service(data_dir)
    try:
        service.execute(job_id, overrides=overrides or {})
    except ValueError as exc:
        return _error(str(exc) or "replacement_job_invalid_state", stage="execute", status=409)
    except Exception:
        return _error("replacement_execute_failed", stage="execute", status=500)
    return video_job_response(load_job(data_dir, "video", job_id))


def retry_video_job(data_dir, job_id, segment_indices):
    if not _valid_job_id("video", job_id) or not load_job(data_dir, "video", job_id):
        return _error("replacement_job_not_found", stage="retry", status=404)
    service = build_video_service(data_dir)
    try:
        service.retry(job_id, _normalize_segment_indices(segment_indices))
    except ValueError as exc:
        code = str(exc) or "replacement_job_not_retryable"
        status = 404 if code == "replacement_job_not_found" else 409
        return _error(code, stage="retry", status=status)
    except Exception:
        return _error("replacement_retry_failed", stage="retry", status=500)
    return video_job_response(load_job(data_dir, "video", job_id))


def concat_video_job(data_dir, job_id):
    if not _valid_job_id("video", job_id) or not load_job(data_dir, "video", job_id):
        return _error("replacement_job_not_found", stage="concat", status=404)
    service = build_video_service(data_dir)
    try:
        service.concat(job_id)
    except ValueError as exc:
        return _error(str(exc) or "replacement_job_not_ready_for_concat", stage="concat", status=409)
    except Exception:
        return _error("replacement_concat_failed", stage="concat", status=500)
    return video_job_response(load_job(data_dir, "video", job_id))


def cancel_video_job(data_dir, job_id):
    if not _valid_job_id("video", job_id) or not load_job(data_dir, "video", job_id):
        return _error("replacement_job_not_found", stage="cancel", status=404)
    service = build_video_service(data_dir)
    try:
        service.cancel(job_id)
    except ValueError as exc:
        code = str(exc) or "replacement_job_not_found"
        status = 404 if code == "replacement_job_not_found" else 409
        return _error(code, stage="cancel", status=status)
    except Exception:
        return _error("replacement_cancel_failed", stage="cancel", status=500)
    return video_job_response(load_job(data_dir, "video", job_id))


_VIDEO_SEGMENT_FIELDS = (
    "index", "start", "end", "status", "qcStatus", "audioStatus",
    "segmentType", "stage", "stageLabel", "elapsedSec", "etaSec",
    "error", "errorId", "progressText",
)


def _public_video_segments(segments):
    result = []
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        result.append({key: segment.get(key) for key in _VIDEO_SEGMENT_FIELDS if key in segment})
    return result


def video_job_response(job):
    job = job if isinstance(job, dict) else {}
    import replacement_service
    scrubbed = replacement_service.public_job(job)
    output_path = str(job.get("outputPath") or "").strip()
    available = bool(
        str(job.get("status") or "") in ("completed", "done")
        and output_path
        and os.path.isfile(output_path)
    )
    output_filename = os.path.basename(output_path) if available else ""
    return {
        "ok": True,
        "jobId": str(scrubbed.get("id") or job.get("id") or ""),
        "taskType": "video",
        "status": str(scrubbed.get("status") or ""),
        "stage": str(scrubbed.get("stage") or ""),
        "progressText": str(scrubbed.get("progressText") or ""),
        "source": scrubbed.get("source") if isinstance(scrubbed.get("source"), dict) else {},
        "sourceContext": scrubbed.get("sourceContext") if isinstance(scrubbed.get("sourceContext"), dict) else {},
        "segments": _public_video_segments(scrubbed.get("segments")),
        "diagnostics": scrubbed.get("diagnostics") if isinstance(scrubbed.get("diagnostics"), dict) else {},
        "error": str(scrubbed.get("error") or ""),
        "handoffId": str(scrubbed.get("handoffId") or job.get("handoffId") or ""),
        "download": {"available": available, "filename": output_filename},
        "createdAt": scrubbed.get("createdAt") or 0,
        "updatedAt": scrubbed.get("updatedAt") or 0,
    }


def final_media_path(data_dir, job_id, filename):
    if not _valid_job_id("video", job_id):
        return None, "bad_path", 400
    job = load_job(data_dir, "video", job_id)
    if not job:
        return None, "not_found", 404
    output_path = str(job.get("outputPath") or "").strip()
    if not output_path or not os.path.isfile(output_path):
        return None, "not_found", 404
    resolved = os.path.abspath(output_path)
    name = str(filename or "").strip()
    if name and (name != os.path.basename(name.replace("\\", "/")) or name != os.path.basename(resolved)):
        return None, "bad_path", 400
    sandbox = os.path.abspath(data_dir)
    if resolved != sandbox and not resolved.startswith(sandbox + os.sep):
        return None, "forbidden", 403
    return resolved, "", 200


def start_note_job(data_dir, fields, files):
    url_parts = _safe_url_parts((fields or {}).get("sourceUrl"))
    if not url_parts:
        return _error("replacement_invalid_source_url")
    images = _image_files(files, {"replacementImages"})
    if not images:
        return _error("replacement_note_missing_images")
    validation_error = _validate_images(images)
    if validation_error:
        return validation_error
    job_id = xhs_note_replacement.new_job_id()
    saved_images = _write_upload_files(data_dir, "note", job_id, images)
    files_metadata = _file_metadata(images)
    for index, (_field, saved_name, _path, _size) in enumerate(saved_images):
        if index < len(files_metadata):
            files_metadata[index]["previewFilename"] = saved_name
    selling_points = [
        _sanitize_note_text(item.strip())
        for item in re.split("[,\\uFF0C\\n]+", str((fields or {}).get("sellingPoints") or ""))
        if item.strip()
    ]
    material = {
        "id": "web-note-source",
        "type": "image",
        "platform": "xhs",
        "title": "replacement web note source",
        "sourceUrl": (fields or {}).get("sourceUrl") or "",
        "sourceDownloadPath": _upload_root(data_dir, "note", job_id),
        "files": [filename for _field, filename, _path, _size in saved_images],
    }
    business_input = {
        "name": _sanitize_note_text((fields or {}).get("businessName") or "your business"),
        "region": _sanitize_note_text((fields or {}).get("region") or ""),
        "sellingPoints": selling_points,
        "audience": _sanitize_note_text((fields or {}).get("audience") or ""),
        "tone": _sanitize_note_text((fields or {}).get("tone") or ""),
    }
    assets = [
        {"slotIndex": index, "assetId": "web-%d" % index, "filePath": path}
        for index, (_field, _filename, path, _size) in enumerate(saved_images, start=1)
    ]
    template = xhs_note_replacement.build_template(material)
    preview = xhs_note_replacement.build_replacement_preview(template, business_input, assets)
    now = time.time()
    source_job = {
        "id": job_id,
        "status": "preview",
        "templateId": template.get("id"),
        "template": template,
        "businessInput": business_input,
        "slotMappings": preview.get("slotMappings") or [],
        "copyCandidates": preview.get("copyCandidates") or [],
        "selectedCopyIndex": preview.get("selectedCopyIndex") or 0,
        "aiSlotCount": preview.get("aiSlotCount") or 0,
        "createdAt": now,
        "updatedAt": now,
    }
    xhs_note_replacement.save_job(data_dir, source_job)
    job = {
        "id": job_id,
        "taskType": "note",
        "status": "preview",
        "stage": "preview_created",
        "progressText": "Phase 0 note preview created",
        "source": url_parts,
        "files": files_metadata,
        "xhsJobId": job_id,
        "imageSlots": _sanitize_note_value(template.get("imageSlots") or []),
        "slotMappings": _sanitize_note_value(preview.get("slotMappings") or []),
        "copyCandidates": _sanitize_note_value(preview.get("copyCandidates") or []),
        "draftMaterialId": "",
        "createdAt": now,
        "updatedAt": now,
    }
    _write_job(data_dir, "note", job)
    return {"ok": True, "jobId": job_id, "taskType": "note", "status": "preview", "stage": "preview_created"}
