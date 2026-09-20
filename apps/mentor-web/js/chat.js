lucide.createIcons();

const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const chatThread = document.getElementById("chatThread");
const threadInner = chatThread.querySelector(".max-w-3xl");

// Ambil credentials dari config.js — jangan hardcode di sini
const SUPABASE_URL = window.AKSARAKU_CONFIG?.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = window.AKSARAKU_CONFIG?.SUPABASE_ANON_KEY || '';
const supabaseClient = (window.supabase && SUPABASE_URL && SUPABASE_ANON_KEY)
  ? window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null;
const sessionList = document.getElementById('sessionList');
const sessionStatus = document.getElementById('sessionStatus');
const chatHistoryPanel = document.getElementById('chatHistoryPanel');
const CHAT_SESSIONS_TABLE = 'chat_sessions';
const CHAT_MESSAGES_TABLE = 'chat_messages';
const DEFAULT_SESSION_TITLE = 'Sesi chat baru';
let currentSessionId = null;
let currentSessionTitle = DEFAULT_SESSION_TITLE;
let currentUserId = null;
const CHAT_CONTEXT = document.body.dataset.role || 'user';
let isCreatingNewSession = false;

function getSessionStorageKey() {
    return `aksaraku_chat_session_id_${CHAT_CONTEXT}_${currentUserId}`;
}

const BACKEND_CHAT_URL = `${window.AKSARAKU_CONFIG.API_BASE_URL}/chat`;
const BACKEND_CHAT_STREAM_URL = `${window.AKSARAKU_CONFIG.API_BASE_URL}/chat/stream`;

// Enable / disable send button based on input content
function autosizeChatInput() {
  if (!chatInput) return;
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
}

chatInput.addEventListener("input", () => {
  sendBtn.disabled = chatInput.value.trim().length === 0;
  autosizeChatInput();
});

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (chatInput.value.trim()) chatForm.requestSubmit();
  }
});

autosizeChatInput();

function formatTime() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, "0");
    const m = String(now.getMinutes()).padStart(2, "0");
    return `${h}:${m}`;
}

function scrollToBottom() {
    chatThread.scrollTo({ top: chatThread.scrollHeight, behavior: "smooth" });
}

function clearChatThread() {
    threadInner.innerHTML = '';
}

function renderSessionStatus(text) {
    if (sessionStatus) {
        sessionStatus.textContent = text;
    }
}

async function getSupabaseSession() {
    if (!supabaseClient) return null;

    try {
        const { data: { session }, error } = await supabaseClient.auth.getSession();
        if (error) throw error;
        return session;
    } catch (error) {
        console.error('Gagal mendapatkan session Supabase:', error);
        return null;
    }
}

async function loadSessionList() {
    if (!supabaseClient || !currentUserId || !sessionList) return;

    const { data, error } = await supabaseClient
        .from(CHAT_SESSIONS_TABLE)
        .select('id,title,updated_at')
        .eq('user_id', currentUserId)
        .order('updated_at', { ascending: false })
        .limit(6);

    if (error) {
        console.error('Gagal memuat sesi chat:', error);
        return;
    }

    if (!data || data.length === 0) {
        sessionList.innerHTML = '<p class="text-xs leading-relaxed text-[#9CA3AF]">Belum ada sesi chat. Klik Chat Baru untuk mulai.</p>';
        return;
    }

    sessionList.innerHTML = '';
    data.forEach((session) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex items-center gap-2 w-full mb-1 group';

        const button = document.createElement('button');
        button.type = 'button';
        const isActive = (session.id === currentSessionId);
        
        button.className = `flex-1 text-left rounded-xl border px-3 py-2 text-xs truncate transition-colors ${
            isActive 
                ? 'bg-white/10 border-purple-500/50 text-white shadow-sm' 
                : 'border-white/5 bg-[#111827] text-[#D1D5DB] hover:border-purple-500/40 hover:bg-white/5'
        }`;
        
        button.textContent = session.title || 'Sesi chat baru';
        button.title = session.title || 'Sesi chat baru';
        button.addEventListener('click', () => switchChatSession(session.id));
        
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.title = 'Hapus riwayat ini';
        deleteBtn.className = 'text-[#6B7280] hover:text-red-400 p-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity';
        deleteBtn.innerHTML = '<i data-lucide="trash-2" class="w-3.5 h-3.5"></i>';
        deleteBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (confirm('Hapus sesi chat ini?')) {
                await supabaseClient.from(CHAT_SESSIONS_TABLE).delete().eq('id', session.id);
                if (currentSessionId === session.id) {
                    currentSessionId = null;
                    localStorage.removeItem(getSessionStorageKey());
                    clearChatThread();
                }
                loadSessionList();
            }
        });

        wrapper.appendChild(button);
        wrapper.appendChild(deleteBtn);
        sessionList.appendChild(wrapper);
    });
    
    if (window.lucide) {
        window.lucide.createIcons();
    }
}

async function createChatSession(title = DEFAULT_SESSION_TITLE) {
    if (!supabaseClient || !currentUserId) return null;

    const { data, error } = await supabaseClient
        .from(CHAT_SESSIONS_TABLE)
        .insert({ user_id: currentUserId, title })
        .select('id,title')
        .single();

    if (error) {
        console.error('Gagal membuat sesi chat:', error);
        return null;
    }

    currentSessionId = data?.id || null;
    currentSessionTitle = data?.title || DEFAULT_SESSION_TITLE;
    if (currentSessionId) {
        localStorage.setItem(getSessionStorageKey(), currentSessionId);
    }

    await loadSessionList();
    return currentSessionId;
}

async function updateSessionTitle(sessionId, title) {
    if (!supabaseClient || !sessionId || !title) return;

    const { error } = await supabaseClient
        .from(CHAT_SESSIONS_TABLE)
        .update({ title })
        .eq('id', sessionId);

    if (error) {
        console.error('Gagal mengupdate judul sesi:', error);
    }
}

async function getCurrentSessionId() {
    if (!supabaseClient || !currentUserId) return null;
    if (currentSessionId) return currentSessionId;

    const storedSessionId = localStorage.getItem(getSessionStorageKey());
    if (storedSessionId) {
        const { data, error } = await supabaseClient
            .from(CHAT_SESSIONS_TABLE)
            .select('id')
            .eq('id', storedSessionId)
            .eq('user_id', currentUserId)
            .single();

        if (!error && data) {
            currentSessionId = storedSessionId;
            return currentSessionId;
        }
    }

    const { data, error } = await supabaseClient
        .from(CHAT_SESSIONS_TABLE)
        .select('id')
        .eq('user_id', currentUserId)
        .order('updated_at', { ascending: false })
        .limit(1)
        .single();

    if (!error && data) {
        currentSessionId = data.id;
        localStorage.setItem(getSessionStorageKey(), currentSessionId);
        return currentSessionId;
    }

    return createChatSession();
}

async function ensureChatSession() {
    if (!supabaseClient) return null;

    const session = await getSupabaseSession();
    if (!session?.user) return null;

    currentUserId = session.user.id;
    
    if (isCreatingNewSession || !currentSessionId) {
        isCreatingNewSession = false;
        const storedSessionId = localStorage.getItem(getSessionStorageKey());
        if (!storedSessionId) {
            return createChatSession();
        }
    }
    
    return getCurrentSessionId();
}

function normalizeSessionTitle(text) {
    if (!text) return DEFAULT_SESSION_TITLE;

    let title = text.trim();
    if (title.length > 50) {
        title = title.slice(0, 50).trim();
        const lastSpace = title.lastIndexOf(' ');
        if (lastSpace > 0) {
            title = title.slice(0, lastSpace);
        }
        title += '...';
    }

    return title;
}

async function updateSessionTitleFromMessage(sessionId, messageText) {
    if (!sessionId || !messageText) return;

    const normalized = normalizeSessionTitle(messageText);
    if (normalized === DEFAULT_SESSION_TITLE) return;

    if (normalized !== currentSessionTitle) {
        currentSessionTitle = normalized;
        await updateSessionTitle(sessionId, normalized);
        await loadSessionList();
    }
}

async function saveChatMessage(sessionId, role, text) {
    if (!supabaseClient || !sessionId || !text) return;

    const { error } = await supabaseClient
        .from(CHAT_MESSAGES_TABLE)
        .insert({ session_id: sessionId, role, content: text });

    if (error) {
        console.error('Gagal menyimpan pesan chat:', error);
    }
}

async function loadChatMessages(sessionId) {
    if (!supabaseClient || !sessionId) return [];

    const { data, error } = await supabaseClient
        .from(CHAT_MESSAGES_TABLE)
        .select('role,content,inserted_at')
        .eq('session_id', sessionId)
        .order('inserted_at', { ascending: true });

    if (error) {
        console.error('Gagal memuat pesan chat:', error);
        return [];
    }

    return data || [];
}

async function switchChatSession(sessionId) {
    if (!sessionId || sessionId === currentSessionId) return;

    currentSessionId = sessionId;
    isCreatingNewSession = false;
    localStorage.setItem(getSessionStorageKey(), sessionId);
    clearChatThread();
    await loadSessionList(); // Update UI active highlight
    await loadSessionMessages(sessionId);
    renderSessionStatus('Riwayat sesi dimuat.');
}

async function loadSessionMessages(sessionId) {
    const messages = await loadChatMessages(sessionId);
    if (!messages.length) return;

    // Deduplikasi pesan kembar berurutan (mencegah pesan ganda saat refresh)
    const deduped = [];
    for (let i = 0; i < messages.length; i++) {
        const current = messages[i];
        const prev = deduped[deduped.length - 1];
        if (prev && prev.role === current.role && (prev.content || "").trim() === (current.content || "").trim()) {
            continue; // Lewati pesan duplikat
        }
        deduped.push(current);
    }

    deduped.forEach((msg) => {
        if (msg.role === 'user') {
            appendUserMessage(msg.content);
        } else {
            appendAiReply(msg.content);
        }
    });

    scrollToBottom();
}

async function initChatSessionHistory() {
    const session = await getSupabaseSession();
    if (!session || !session.user) {
        return;
    }

    chatHistoryPanel?.classList.remove('hidden');
    currentUserId = session.user.id;
    await loadSessionList();
    const sessionId = await getCurrentSessionId();
    if (sessionId) {
        clearChatThread();
        await loadSessionMessages(sessionId);
    }
}

function appendUserMessage(text) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex flex-col items-end animate-fadeUp";
    wrapper.innerHTML = `
      <div class="bg-bubbleUser rounded-2xl rounded-tr-sm px-4 py-3.5 max-w-[85%]">
        <p class="text-sm leading-relaxed text-[#F3F4F6]"></p>
      </div>
      <span class="text-[11px] text-[#6B7280] mt-1.5 mr-1">Terkirim • ${formatTime()}</span>
    `;
    wrapper.querySelector("p").textContent = text;
    threadInner.appendChild(wrapper);
    return wrapper;
}

function getAiAvatarImgHtml() {
    const isSubDir = window.location.pathname.includes('/admin/') || window.location.pathname.includes('/teacher/');
    const defaultRelPath = isSubDir ? '../image/logo.png' : './image/logo.png';
    const existingLogo = document.querySelector('img[alt="Aksaraku"], .brand-logo');
    const logoSrc = existingLogo ? existingLogo.getAttribute('src') : defaultRelPath;
    return `<img src="${logoSrc}" alt="Aksaraku" class="h-5 w-5 object-contain" onerror="if(!this.dataset.fallback){this.dataset.fallback='1';this.src='${defaultRelPath}';}" />`;
}

function appendTypingIndicator() {
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-3 animate-fadeUp";
    wrapper.id = "typingIndicator";
    wrapper.innerHTML = `
      <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-md shadow-purple-900/30">
        ${getAiAvatarImgHtml()}
      </div>
            <div class="ai-thinking-bubble bg-bubbleAi border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3.5">
                <div class="flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full bg-[#6B7280] animate-bounce" style="animation-delay:0ms"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-[#6B7280] animate-bounce" style="animation-delay:150ms"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-[#6B7280] animate-bounce" style="animation-delay:300ms"></span>
                    <span class="ai-thinking-label text-xs text-[#9CA3AF]">AI sedang menyusun jawaban</span>
        </div>
      </div>
    `;
    threadInner.appendChild(wrapper);
    lucide.createIcons();
    return wrapper;
}

function appendAiReply(text) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-3 animate-fadeUp";
    wrapper.innerHTML = `
      <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-md shadow-purple-900/30">
        ${getAiAvatarImgHtml()}
      </div>
    <div class="ai-reply-bubble bg-bubbleAi border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3.5 max-w-[85%]">
        <p class="text-sm leading-relaxed text-[#F3F4F6] whitespace-pre-wrap"></p>
      </div>
    `;
    wrapper.querySelector("p").innerHTML = renderChatMarkdown(removeAccuracyNotice(text));
    threadInner.appendChild(wrapper);
    lucide.createIcons();
    return wrapper;
}

function escapeChatHtml(text) {
    return String(text ?? '').replace(/[&<>'"]/g, (character) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[character]));
}

function renderChatMarkdown(text) {
    const lines = escapeChatHtml(text).replace(/\r\n?/g, '\n').split('\n');
    const inline = (value) => value
        .replace(/`([^`\n]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
        .replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    const output = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index].trim();
        if (!line) {
            index += 1;
            continue;
        }
        const heading = line.match(/^#{1,6}\s+(.+)$/);
        if (heading) {
            output.push(`<h3>${inline(heading[1])}</h3>`);
            index += 1;
            continue;
        }
        const item = line.match(/^([-*+] |\d+[.)] |[a-zA-Z][.)] )(.*)$/);
        if (item) {
            const ordered = /^\d|^[a-zA-Z]/.test(item[1]);
            const alpha = /^[a-zA-Z]/.test(item[1]);
            const items = [];
            while (index < lines.length) {
                const current = lines[index].trim();
                const match = current.match(ordered
                    ? /^(?:\d+[.)]|[a-zA-Z][.)]) (.*)$/
                    : /^[-*+] (.*)$/);
                if (!match) break;
                items.push(`<li>${inline(match[1])}</li>`);
                index += 1;
            }
            output.push(`<${ordered ? 'ol' : 'ul'}${alpha ? ' class="chat-list-alpha"' : ''}>${items.join('')}</${ordered ? 'ol' : 'ul'}>`);
            continue;
        }
        const paragraph = [line];
        index += 1;
        while (index < lines.length && lines[index].trim() && !/^#{1,6}\s+/.test(lines[index].trim()) && !/^([-*+] |\d+[.)] |[a-zA-Z][.)] )/.test(lines[index].trim())) {
            paragraph.push(lines[index].trim());
            index += 1;
        }
        output.push(`<p>${inline(paragraph.join(' '))}</p>`);
    }
    return `<div class="chat-markdown">${output.join('')}</div>`;
}

function removeAccuracyNotice(text) {
    return String(text ?? '')
        .replace(/\*{0,2}\s*Tidak ada nilai akurasi yang tersedia dalam dokumen\s*\*{0,2}\s*[.!]?/gi, '')
        .replace(/[ \t]{2,}/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function truncateText(text, maxChars = 140) {
    if (!text) return "";
    return text.length <= maxChars ? text : `${text.slice(0, maxChars).trim()}…`;
}

function createSourcesHtml(sources) {
    if (!Array.isArray(sources) || sources.length === 0) {
        return "";
    }

    // Kelompokkan dan deduplikasi sumber berdasarkan nama file agar rapi dan ringkas
    const fileMap = new Map();
    sources.forEach((source) => {
        const rawName = source.pdf_name || source.file_name || "Dokumen Referensi";
        const cleanName = rawName.replace(/[-_]/g, " ").replace(/\.pdf$/i, "").trim();
        const displayName = cleanName.charAt(0).toUpperCase() + cleanName.slice(1);

        if (!fileMap.has(rawName)) {
            fileMap.set(rawName, {
                rawName,
                displayName,
                snippets: [],
            });
        }
        const snippet = (source.content || source.snippet || "").trim();
        if (snippet && fileMap.get(rawName).snippets.length < 2) {
            fileMap.get(rawName).snippets.push(truncateText(snippet, 120));
        }
    });

    const fileList = Array.from(fileMap.values()).slice(0, 3);
    if (fileList.length === 0) return "";

    return `
      <details class="group mt-3 border border-white/10 rounded-xl bg-[#111827]/70 overflow-hidden text-xs transition-all duration-200">
        <summary class="flex items-center justify-between px-3.5 py-2 cursor-pointer select-none text-slate-300 hover:text-white hover:bg-white/5 transition-colors">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-purple-400 font-semibold text-[11px] uppercase tracking-wider">📚 Sumber Referensi:</span>
            <span class="text-slate-200 font-medium">${fileList.map(f => escapeChatHtml(f.displayName)).join(", ")}</span>
          </div>
          <svg class="w-3.5 h-3.5 text-slate-400 transition-transform duration-200 group-open:rotate-180 shrink-0 ml-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
          </svg>
        </summary>
        <div class="p-3 border-t border-white/5 space-y-2 bg-[#0B0F17]/60">
          ${fileList.map(f => `
            <div class="p-2.5 rounded-lg bg-white/5 border border-white/5 space-y-1">
              <div class="flex items-center gap-1.5 font-medium text-purple-300 text-xs">
                <span>📄 ${escapeChatHtml(f.displayName)}</span>
              </div>
              ${f.snippets.map(snip => `
                <p class="text-[11px] text-slate-400 leading-relaxed italic">"${escapeChatHtml(snip)}"</p>
              `).join("")}
            </div>
          `).join("")}
        </div>
      </details>
    `;
}

function appendAiReplyWithSources(answer, sources) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-3 animate-fadeUp";
    const sourcesHtml = createSourcesHtml(sources);
    wrapper.innerHTML = `
      <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-md shadow-purple-900/30">
        ${getAiAvatarImgHtml()}
      </div>
      <div class="ai-reply-bubble bg-bubbleAi border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3.5 max-w-[85%] space-y-2">
        <div>
          <p class="text-sm leading-relaxed text-[#F3F4F6] whitespace-pre-wrap"></p>
        </div>
        ${sourcesHtml ? `<div class="sources-container">${sourcesHtml}</div>` : ''}
      </div>
    `;

    wrapper.querySelector("p").innerHTML = renderChatMarkdown(removeAccuracyNotice(answer));
    threadInner.appendChild(wrapper);
    lucide.createIcons();
    return wrapper;
}

function createStreamingAiReplyBubble() {
    const wrapper = document.createElement("div");
    wrapper.className = "flex items-start gap-3 animate-fadeUp";
    wrapper.innerHTML = `
      <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-md shadow-purple-900/30">
        ${getAiAvatarImgHtml()}
      </div>
      <div class="ai-reply-bubble bg-bubbleAi border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3.5 max-w-[85%] space-y-2">
        <div class="ai-text-container">
          <p class="text-sm leading-relaxed text-[#F3F4F6] whitespace-pre-wrap"><span class="inline-block w-2 h-4 bg-purple-400 animate-pulse align-middle ml-1"></span></p>
        </div>
        <div class="sources-container hidden"></div>
      </div>
    `;
    threadInner.appendChild(wrapper);
    lucide.createIcons();
    const textEl = wrapper.querySelector(".ai-text-container p");
    const sourcesContainer = wrapper.querySelector(".sources-container");
    return {
        wrapper,
        updateText: (rawText) => {
            textEl.innerHTML = renderChatMarkdown(removeAccuracyNotice(rawText)) + '<span class="inline-block w-1.5 h-3.5 bg-purple-400 animate-pulse align-middle ml-1"></span>';
        },
        finalize: (rawText, sources = []) => {
            textEl.innerHTML = renderChatMarkdown(removeAccuracyNotice(rawText));
            const claimsNoInfo = /tidak\s+(ditemukan|ada|terdapat|tercantum|disebutkan|tersedia|memuat)/i.test(rawText);
            if (!claimsNoInfo && Array.isArray(sources) && sources.length > 0) {
                const html = createSourcesHtml(sources);
                if (html) {
                    sourcesContainer.innerHTML = html;
                    sourcesContainer.classList.remove("hidden");
                } else {
                    sourcesContainer.classList.add("hidden");
                }
            } else {
                sourcesContainer.classList.add("hidden");
            }
        }
    };
}

async function fetchChatResponse(question) {
    const session = await getSupabaseSession();
    const headers = { "Content-Type": "application/json" };
    if (session?.access_token) {
        headers.Authorization = `Bearer ${session.access_token}`;
    }

    const response = await fetch(BACKEND_CHAT_URL, {
        method: "POST",
        headers,
        body: JSON.stringify({ question }),
    });

    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.error || "Gagal memanggil endpoint /chat");
    }

    const payload = Array.isArray(result) ? result[0] : result;
    if (!payload || typeof payload.answer !== "string") {
        throw new Error("Respons API tidak valid atau kosong.");
    }

    return {
        answer: removeAccuracyNotice(payload.answer),
        sources: Array.isArray(payload.sources) ? payload.sources : [],
    };
}

function userAskedForSources(text) {
    if (!text) return false;
    return /\b(sumber|dokumen|referensi|rujukan|bukti|source|sumbernya|dokumennya|referensinya)\b/i.test(text);
}

async function handleSend(text) {
  const trimmed = text.trim();
  if (!trimmed) return;

  const sessionId = await ensureChatSession();
  appendUserMessage(trimmed);
  if (sessionId) {
    // Backend /chat dan /chat/stream sudah otomatis menyimpan pesan user & assistant ke Supabase.
    await updateSessionTitleFromMessage(sessionId, trimmed);
  }

  chatInput.value = "";
  autosizeChatInput();
  sendBtn.disabled = true;
  scrollToBottom();

  const typing = appendTypingIndicator();
  scrollToBottom();

  const session = await getSupabaseSession();
  const headers = { "Content-Type": "application/json" };
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }

  let streamBubble = null;
  let accumulatedText = "";
  let receivedSources = [];

  try {
    const response = await fetch(BACKEND_CHAT_STREAM_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({ question: trimmed, session_id: sessionId }),
    });

    if (!response.ok || !response.body) {
      throw new Error("Streaming tidak aktif, mencoba mode reguler...");
    }

    typing.remove();
    streamBubble = createStreamingAiReplyBubble();
    scrollToBottom();

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const ev of events) {
        if (!ev.trim()) continue;
        const lines = ev.split("\n");
        let eventType = "message";
        let dataStr = "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            dataStr = line.slice(6).trim();
          }
        }

        if (eventType === "token" && dataStr) {
          try {
            const data = JSON.parse(dataStr);
            accumulatedText += data.text || "";
            streamBubble.updateText(accumulatedText);
            scrollToBottom();
          } catch (e) {}
        } else if (eventType === "metadata" && dataStr) {
          try {
            const data = JSON.parse(dataStr);
            if (Array.isArray(data.sources)) {
              receivedSources = data.sources;
            }
          } catch (e) {}
        }
      }
    }

    const claimsNoInfo = /tidak\s+(ditemukan|ada|terdapat|tercantum|disebutkan|tersedia|memuat)/i.test(accumulatedText);
    const showSources = !claimsNoInfo && receivedSources.length > 0;
    streamBubble.finalize(accumulatedText, showSources ? receivedSources : []);
    scrollToBottom();
  } catch (error) {
    if (typing && typing.parentNode) typing.remove();
    if (!accumulatedText) {
      try {
        const { answer, sources } = await fetchChatResponse(trimmed);
        const claimsNoInfo = /tidak\s+(ditemukan|ada|terdapat|tercantum|disebutkan|tersedia|memuat)/i.test(answer);
        const includeSources = !claimsNoInfo && sources.length > 0;
        if (includeSources) {
          appendAiReplyWithSources(answer, sources);
        } else {
          appendAiReply(answer);
        }
      } catch (fallbackErr) {
        console.error(fallbackErr);
        appendAiReply("Maaf, terjadi kesalahan saat memproses request: " + (fallbackErr.message || "Unknown error"));
      }
    } else {
      console.error("Stream interrupted:", error);
    }
  } finally {
    sendBtn.disabled = false;
    scrollToBottom();
  }
}


// Form submit handler
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await handleSend(chatInput.value);
});

// Suggestion pill click handler
document.querySelectorAll(".suggestion-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
        handleSend(pill.textContent);
    });
});

// Chat Baru button
document.getElementById("newResearchBtn").addEventListener("click", async () => {
    clearChatThread();
    currentSessionId = null;
    isCreatingNewSession = true;
    localStorage.removeItem(getSessionStorageKey());
    renderSessionStatus('Sesi baru dibuat. Silakan mulai chat.');
    chatInput.focus();
    loadSessionList(); // Clear active highlight
});

async function initChatSessionHistoryWrapper() {
    await initChatSessionHistory();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChatSessionHistoryWrapper);
} else {
    initChatSessionHistoryWrapper();
}