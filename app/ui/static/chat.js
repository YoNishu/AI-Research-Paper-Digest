// --- State ---
let currentConversationId = null;

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    loadConversations();
    if (INITIAL_CONVERSATION_ID) {
        loadConversation(INITIAL_CONVERSATION_ID);
    }
});

// --- Conversations ---
async function loadConversations() {
    const res = await fetch('/conversations');
    const convs = await res.json();
    const list = document.getElementById('conversationList');
    list.innerHTML = '';
    convs.forEach(c => {
        const el = document.createElement('div');
        el.className = 'sidebar-item' + (c.id === currentConversationId ? ' active' : '');
        el.innerHTML = `<span class="conv-title">${escapeHtml(c.title)}</span>
            <button class="delete-btn" onclick="event.stopPropagation(); deleteConversation(${c.id})">×</button>`;
        el.onclick = () => loadConversation(c.id);
        list.appendChild(el);
    });
}

async function loadConversation(id) {
    currentConversationId = id;
    const res = await fetch(`/conversations/${id}/messages`);
    const msgs = await res.json();
    const container = document.getElementById('messages');
    container.innerHTML = '';
    msgs.forEach(m => {
        if (m.role === 'user' || m.role === 'assistant') {
            appendMessage(m.role, m.content || '');
        }
    });
    container.scrollTop = container.scrollHeight;

    // Update header
    const convRes = await fetch('/conversations');
    const convs = await convRes.json();
    const conv = convs.find(c => c.id === id);
    if (conv) {
        document.getElementById('chatHeader').innerHTML = `
            <span>${escapeHtml(conv.title)}</span>
            ${conv.research_interest ? `<span class="interest-badge">${escapeHtml(conv.research_interest)}</span>` : ''}
            <button class="btn btn-sm" onclick="setResearchInterest()">Set Interest</button>`;
    }
    loadConversations();
    window.history.replaceState(null, '', `/ui/chat/${id}`);
}

async function newChat() {
    const interest = prompt('Research interest (optional):');
    const res = await fetch('/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ research_interest: interest || null })
    });
    const conv = await res.json();
    await loadConversations();
    loadConversation(conv.id);
}

async function deleteConversation(id) {
    if (!confirm('Delete this conversation?')) return;
    await fetch(`/conversations/${id}`, { method: 'DELETE' });
    if (currentConversationId === id) {
        currentConversationId = null;
        document.getElementById('messages').innerHTML = '';
        document.getElementById('chatHeader').innerHTML = '<span>Select or start a conversation</span>';
        window.history.replaceState(null, '', '/ui/chat');
    }
    loadConversations();
}

async function setResearchInterest() {
    if (!currentConversationId) return;
    const interest = prompt('Enter your research interest:');
    if (interest === null) return;
    await fetch(`/conversations/${currentConversationId}/research-interest`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ research_interest: interest })
    });
    loadConversation(currentConversationId);
}

// --- Messaging ---
let streamingRawText = '';

async function sendMessage(event) {
    event.preventDefault();
    const input = document.getElementById('messageInput');
    const text = input.value.trim();
    if (!text) return;

    const btn = document.getElementById('sendBtn');
    btn.disabled = true;
    input.value = '';
    appendMessage('user', text);

    const body = { message: text, conversation_id: currentConversationId };

    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let assistantEl = null;
        let buffer = '';
        streamingRawText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const payload = line.slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    const data = JSON.parse(payload);
                    if (data.type === 'meta') {
                        if (!currentConversationId) {
                            currentConversationId = data.conversation_id;
                            window.history.replaceState(null, '', `/ui/chat/${data.conversation_id}`);
                        }
                    } else if (data.type === 'tool') {
                        appendToolStatus(data.name);
                    } else if (data.type === 'text') {
                        if (!assistantEl) {
                            assistantEl = appendMessage('assistant', '');
                        }
                        streamingRawText += data.content;
                        // Live preview: render markdown as it streams
                        assistantEl.querySelector('.msg-content').innerHTML = renderMarkdown(streamingRawText);
                    }
                } catch (e) { /* skip */ }
            }
        }
        // Final render after stream completes
        if (assistantEl) {
            assistantEl.querySelector('.msg-content').innerHTML = renderMarkdown(streamingRawText);
        }
    } catch (err) {
        appendMessage('assistant', 'Error: ' + err.message);
    }

    btn.disabled = false;
    loadConversations();
    const container = document.getElementById('messages');
    container.scrollTop = container.scrollHeight;
}

// --- DOM helpers ---
function appendMessage(role, content) {
    const container = document.getElementById('messages');
    const el = document.createElement('div');
    el.className = `message ${role}`;
    const rendered = role === 'assistant' && content ? renderMarkdown(content) : escapeHtml(content);
    el.innerHTML = `<div class="msg-role">${role === 'user' ? 'You' : 'Assistant'}</div><div class="msg-content">${rendered}</div>`;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
    return el;
}

function appendToolStatus(name) {
    const container = document.getElementById('messages');
    const el = document.createElement('div');
    el.className = 'tool-status';
    el.innerHTML = `<span class="tool-pill">${escapeHtml(name.replace(/_/g, ' '))}</span>`;
    container.appendChild(el);
}

function escapeHtml(text) {
    if (!text) return '';
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

// --- Markdown renderer (lightweight, no dependencies) ---
function renderMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);

    // Code blocks (```lang ... ```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
        `<pre><code class="lang-${lang || 'text'}">${code.trim()}</code></pre>`
    );

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Headers (### before ## before #)
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold + italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Horizontal rule
    html = html.replace(/^---$/gm, '<hr>');

    // Unordered lists (- item)
    html = html.replace(/^(\s*)- (.+)$/gm, (_, indent, item) => {
        const level = Math.floor(indent.length / 2);
        return `<li style="margin-left:${level * 1.2}em">${item}</li>`;
    });
    // Wrap consecutive <li> in <ul>
    html = html.replace(/((?:<li[^>]*>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

    // Ordered lists (1. item)
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');
    // Wrap consecutive ordered <li> (that aren't already in <ul>)
    html = html.replace(/(?:^<li>.*<\/li>\n?)+/gm, (match) => {
        if (match.includes('style=')) return match; // already handled as unordered
        return `<ol>${match}</ol>`;
    });

    // Links [text](url)
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Line breaks: convert double newlines to paragraphs, single to <br>
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = '<p>' + html + '</p>';

    // Clean up empty paragraphs and paragraph-wrapped block elements
    html = html.replace(/<p>\s*<\/p>/g, '');
    html = html.replace(/<p>(<(?:h[1-4]|ul|ol|pre|hr|blockquote)[^>]*>)/g, '$1');
    html = html.replace(/(<\/(?:h[1-4]|ul|ol|pre|hr|blockquote)>)<\/p>/g, '$1');

    return html;
}
