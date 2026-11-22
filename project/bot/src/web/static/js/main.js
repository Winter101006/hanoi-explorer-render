/**
 * HANOI EXPLORER CHATBOT - CORE WEB LOGIC
 * Tác giả & Phát triển: Phạm Ngọc Huân (@Winter101006)
 * 
 * Chức năng:
 * - Gửi/nhận tin nhắn trò chuyện với Trợ lý AI Du lịch & Ẩm thực Hà Nội
 * - Lưu và quản lý lịch sử trò chuyện 3 ngày qua localStorage
 * - Lọc địa điểm theo danh mục và quận/huyện
 * - Hiển thị thẻ địa điểm trực quan kèm thông tin chi tiết và liên kết Google Maps
 * - Hộp thoại modal xem chi tiết địa chỉ, thời gian, mức giá
 */

// ==========================================================================
// 1. BIẾN TOÀN CỤC & HỆ THỐNG DỮ LIỆU
// ==========================================================================
const placesDataStore = new Map();
const STORAGE_KEY = 'hanoi_explorer_chats_v4';
const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000;

let chatSessions = [];
let currentChatId = null;
let currentCategory = 'all';
let currentDistrict = 'all';
let currentModalPlace = null;
let isSending = false;

// ==========================================================================
// 2. KHỞI TẠO ỨNG DỤNG (DOMContentLoaded)
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    initModalDOM();
    initConfirmModalDOM();
    initCategoryPills();
    initScrollToBottom();
    loadChatsFromStorage();

    const districtSelect = document.getElementById('district-select');
    if (districtSelect) {
        districtSelect.value = 'all';
    }

    const sendBtn = document.getElementById('send-btn');
    const userInput = document.getElementById('user-input');
    const newChatBtn = document.getElementById('new-chat-btn');

    if (sendBtn) {
        sendBtn.addEventListener('click', () => sendMessage());
    }

    if (userInput) {
        userInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.isComposing) {
                e.preventDefault();
                sendMessage();
            }
        });
        userInput.focus();
    }

    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => {
            startNewChat();
            closeMobileSidebar();
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePlaceModal();
            closeConfirmModal();
            closeMobileSidebar();
        }
    });
});

function toggleMobileSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (!sidebar) return;
    const isOpen = sidebar.classList.toggle('mobile-open');
    if (overlay) {
        overlay.classList.toggle('active', isOpen);
    }
}

function closeMobileSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (overlay) overlay.classList.remove('active');
}

// ==========================================================================
// 3. QUẢN LÝ LỊCH SỬ CHAT (LOCALSTORAGE - 3 NGÀY)
// ==========================================================================
function loadChatsFromStorage() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            const now = Date.now();
            chatSessions = Array.isArray(parsed)
                ? parsed.filter(s => s && typeof s === 'object' && typeof s.id === 'string' && typeof s.timestamp === 'number' && (now - s.timestamp) < THREE_DAYS_MS)
                : [];
        } else {
            chatSessions = [];
        }
    } catch (e) {
        console.error("Lỗi khi tải lịch sử chat:", e);
        chatSessions = [];
    }

    if (chatSessions.length === 0) {
        startNewChat(true);
    } else {
        renderHistorySidebar();
        switchToChat(chatSessions[0].id);
    }
}

function saveChatsToStorage() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(chatSessions));
    } catch (e) {
        console.error("Lỗi khi lưu lịch sử chat:", e);
    }
}

function startNewChat(renderAfter = true) {
    const newSession = {
        id: `chat_${Date.now()}`,
        timestamp: Date.now(),
        title: 'Cuộc trò chuyện mới',
        messages: []
    };

    chatSessions.unshift(newSession);
    currentChatId = newSession.id;
    saveChatsToStorage();

    if (renderAfter) {
        renderHistorySidebar();
        renderChatViewport();
    }

    const userInput = document.getElementById('user-input');
    if (userInput) userInput.focus();
}

function switchToChat(chatId) {
    currentChatId = chatId;
    renderHistorySidebar();
    renderChatViewport();
    closeMobileSidebar();
}

function renderHistorySidebar() {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;

    if (chatSessions.length === 0) {
        historyList.innerHTML = `<div class="empty-history-text">Chưa có lịch sử trò chuyện.</div>`;
        return;
    }

    historyList.innerHTML = chatSessions.map(session => {
        const isActive = session.id === currentChatId ? 'active' : '';
        const safeId = escapeHTML(session.id);
        const title = escapeHTML(session.title || 'Cuộc trò chuyện mới');
        return `
            <div class="history-item ${isActive}" onclick="switchToChat('${safeId}')">
                <div class="history-item-content">
                    <i class="fa-regular fa-message"></i>
                    <span title="${title}">${title}</span>
                </div>
                <button class="delete-chat-btn" onclick="deleteChatSession('${safeId}', event)" title="Xóa đoạn chat này">
                    <i class="fa-regular fa-trash-can"></i>
                </button>
            </div>
        `;
    }).join('');
}

function deleteChatSession(chatId, event) {
    if (event) event.stopPropagation();
    chatSessions = chatSessions.filter(s => s.id !== chatId);
    saveChatsToStorage();

    if (chatSessions.length === 0) {
        startNewChat(true);
    } else {
        if (currentChatId === chatId) {
            switchToChat(chatSessions[0].id);
        } else {
            renderHistorySidebar();
        }
    }
}

// ==========================================================================
// 4. HIỂN THỊ VÙNG CHAT (CHAT VIEWPORT)
// ==========================================================================
function renderChatViewport() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    chatMessages.innerHTML = '';
    const currentSession = chatSessions.find(s => s.id === currentChatId);

    if (!currentSession || currentSession.messages.length === 0) {
        renderWelcomeMessage();
        return;
    }

    currentSession.messages.forEach(msg => {
        if (msg.sender === 'user') {
            appendUserMessage(msg.text, false);
        } else {
            appendBotMessage(msg.text, msg.places || [], false);
        }
    });

    scrollToBottom();
}

function renderWelcomeMessage() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const welcomeDiv = document.createElement('div');
    welcomeDiv.className = 'welcome-hero';
    welcomeDiv.innerHTML = `
        <div class="hero-icon"><i class="fa-solid fa-compass"></i></div>
        <h2>Xin chào! Mình là Hanoi Explorer AI</h2>
        <p>Người bạn bản địa đồng hành cùng bạn khám phá ẩm thực, danh lam thắng cảnh, di tích lịch sử và góc cà phê đẹp nhất thủ đô Hà Nội.</p>
        <div class="welcome-suggestions">
            <button class="welcome-chip" onclick="quickSend('Gợi ý những quán phở bò gia truyền ngon nhất phố cổ')">🍜 Phở bò gia truyền phố cổ</button>
            <button class="welcome-chip" onclick="quickSend('Quán cafe yên tĩnh làm việc và học bài ở Cầu Giấy')">☕ Cafe yên tĩnh Cầu Giấy</button>
            <button class="welcome-chip" onclick="quickSend('Các hồ ngắm cảnh hoàng hôn đẹp và thoáng mát ở Hà Nội')">🌅 Hồ ngắm cảnh hoàng hôn</button>
            <button class="welcome-chip" onclick="quickSend('Địa điểm chùa cổ thanh tịnh linh thiêng quanh Hồ Tây')">🛕 Chùa thanh tịnh Hồ Tây</button>
        </div>
    `;
    chatMessages.appendChild(welcomeDiv);
}

function quickSend(promptText) {
    const input = document.getElementById('user-input');
    if (input) {
        input.value = promptText;
        sendMessage();
    }
}

// ==========================================================================
// 5. BỘ LỌC DANH MỤC & QUẬN HUYỆN
// ==========================================================================
function initCategoryPills() {
    const pills = document.querySelectorAll('.pill-btn');
    pills.forEach(btn => {
        btn.addEventListener('click', () => {
            const catCode = btn.getAttribute('data-cat') || 'all';
            pills.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentCategory = catCode;

            const catNames = {
                'all': 'Tất cả danh mục',
                'tam-linh': 'Tâm linh & Đền Chùa',
                'di-tich': 'Di tích & Bảo tàng',
                'ngoai-troi': 'Hồ cảnh quan & Dã ngoại',
                'giai-tri': 'Giải trí & Rạp phim',
                'the-thao': 'Thể thao & Bơi lội',
                'an-uong': 'Ẩm thực & Quán ăn',
                'ca-phe': 'Cà phê & Trà'
            };
            showToast(`Đã lọc danh mục: ${catNames[catCode] || catCode}`);
            const input = document.getElementById('user-input');
            if (input) input.focus();
        });
    });
}

function handleDistrictFilterChange(district) {
    currentDistrict = district || 'all';
    if (district !== 'all') {
        showToast(`Đã lọc khu vực: Quận ${district}`);
    } else {
        showToast("Đã chuyển về toàn bộ khu vực Hà Nội.");
    }
    const input = document.getElementById('user-input');
    if (input) input.focus();
}

// ==========================================================================
// 6. GỬI TIN NHẮN & XỬ LÝ PHẢN HỒI (SEND MESSAGE PIPELINE)
// ==========================================================================
function sendMessage() {
    if (isSending) return;

    const input = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    if (!input) return;

    const message = input.value.trim();
    if (!message) return;
    if (message.length > 500) {
        showToast("Tin nhắn tối đa 500 ký tự, vui lòng rút gọn!");
        return;
    }

    input.value = '';
    isSending = true;
    if (sendBtn) sendBtn.disabled = true;

    // Lấy ngữ cảnh hội thoại gần nhất (kèm danh sách địa điểm rút gọn để tra cứu lượt trước)
    let historyContext = [];
    const currentSession = chatSessions.find(s => s.id === currentChatId);
    if (currentSession && currentSession.messages) {
        historyContext = currentSession.messages.slice(-6).map(m => {
            const entry = {
                role: m.sender === 'user' ? 'user' : 'assistant',
                content: m.text || ''
            };
            if (m.sender !== 'user' && Array.isArray(m.places) && m.places.length > 0) {
                entry.places = m.places.slice(0, 6).map(p => ({
                    id: p.id || '',
                    name: p.name || '',
                    category: p.category || '',
                    category_code: p.category_code || '',
                    district: p.district || '',
                    address: p.address || '',
                    opening_hours: p.opening_hours || '',
                    price_range: p.price_range || '',
                    suitable_for: p.suitable_for || '',
                    weather_fit: p.weather_fit || '',
                    description: p.description || ''
                }));
            }
            return entry;
        });
    }

    // Xóa hero welcome nếu có
    const welcome = document.querySelector('.welcome-hero');
    if (welcome) welcome.remove();

    appendUserMessage(message);
    showSkeletonLoading();

    const payload = {
        message: message,
        category: currentCategory,
        district: currentDistrict,
        history: historyContext
    };

    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(async res => {
        let data = null;
        try {
            data = await res.json();
        } catch (_) {
            data = null;
        }
        if (!res.ok) {
            const errMsg = (data && data.reply) ? data.reply : `Hệ thống trả về mã lỗi ${res.status}. Vui lòng thử lại!`;
            return { status: 'error', reply: errMsg, places: [] };
        }
        return data;
    })
    .then(data => {
        removeSkeletonLoading();
        if (data && data.status === 'success') {
            const places = data.places || [];
            const reply = data.reply || "Dưới đây là một số địa điểm phù hợp dành cho bạn:";
            const followUp = data.follow_up;
            appendBotMessage(followUp && !reply.includes(followUp) ? reply + '\n\n' + followUp : reply, places);
        } else {
            appendBotMessage((data && data.reply) ? data.reply : "Rất tiếc, hệ thống tạm thời gặp trục trặc khi tra cứu. Bạn vui lòng thử lại nhé!");
        }
    })
    .catch(err => {
        console.error("Lỗi gửi tin nhắn:", err);
        removeSkeletonLoading();
        appendBotMessage("Không thể kết nối tới máy chủ. Vui lòng kiểm tra xem server đang chạy chưa và thử lại nhé!");
    })
    .finally(() => {
        isSending = false;
        if (sendBtn) sendBtn.disabled = false;
        if (input) input.focus();
    });
}

function appendUserMessage(text, saveToSession = true) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const msgDiv = document.createElement('div');
    msgDiv.className = 'message user-message';
    msgDiv.innerHTML = `
        <div class="message-content">
            <p>${escapeHTML(text)}</p>
        </div>
    `;

    chatMessages.appendChild(msgDiv);
    scrollToBottom();

    if (saveToSession && currentChatId) {
        const session = chatSessions.find(s => s.id === currentChatId);
        if (session) {
            session.messages.push({ sender: 'user', text: text });
            if (session.messages.length === 1) {
                session.title = text.slice(0, 32) + (text.length > 32 ? '...' : '');
            }
            saveChatsToStorage();
            renderHistorySidebar();
        }
    }
}

function appendBotMessage(text, places = [], saveToSession = true) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot-message';

    // Render danh sách các thẻ địa điểm (Places Grid)
    let gridHTML = '';
    if (places && places.length > 0) {
        gridHTML = `<div class="places-grid">` + places.map(p => {
            const placeId = p.id || `hn_${Math.random().toString(36).substr(2, 9)}`;
            const safePlaceId = escapeHTML(placeId);
            const cleanName = decodeHTMLEntities(p.name || '');
            const cleanPlace = { ...p, name: cleanName, id: placeId };
            placesDataStore.set(placeId, cleanPlace);

            const validCats = new Set(['an-uong', 'ca-phe', 'tam-linh', 'di-tich', 'ngoai-troi', 'giai-tri', 'the-thao', 'unknown']);
            const catCode = validCats.has(p.category_code) ? p.category_code : 'unknown';
            const catName = p.category || 'Địa điểm';
            const shortCatName = formatShortCategory(catName, catCode);
            const shortWeather = formatWeatherBadge(p.weather_fit);
            const districtStr = p.district ? `Q. ${p.district}` : 'Hà Nội';
            const suitStr = p.suitable_for || 'Tất cả đối tượng';
            const balancedName = formatBalancedCardTitle(cleanName);

            const mapsQuery = encodeURIComponent(cleanName + ' ' + (p.address || (districtStr + ' Hà Nội')));

            return `
            <div class="place-card">
                <div class="place-card-body">
                    <div class="place-header">
                        <h4>${escapeHTML(balancedName)}</h4>
                    </div>

                    <div class="place-tags">
                        <span class="sub-badge location"><i class="fa-solid fa-location-dot"></i> ${escapeHTML(districtStr)}</span>
                        <span class="badge-tag ${catCode}" title="${escapeHTML(catName)}">${escapeHTML(shortCatName)}</span>
                        <span class="sub-badge weather"><i class="fa-solid fa-cloud-sun"></i> ${escapeHTML(shortWeather)}</span>
                    </div>

                    <div class="place-meta">
                        <div class="meta-row">
                            <i class="fa-regular fa-clock"></i>
                            <span class="meta-label">Giờ mở cửa:</span>
                            <span class="meta-value">${escapeHTML(p.opening_hours || '08:00 – 22:00')}</span>
                        </div>
                        <div class="meta-row">
                            <i class="fa-solid fa-ticket"></i>
                            <span class="meta-label">Giá vé / Món:</span>
                            <span class="meta-value">${escapeHTML(p.price_range || 'Tham khảo')}</span>
                        </div>
                        <div class="meta-row">
                            <i class="fa-solid fa-users"></i>
                            <span class="meta-label">Phù hợp:</span>
                            <span class="meta-value">${escapeHTML(suitStr)}</span>
                        </div>
                    </div>
                </div>

                <div class="place-actions-row">
                    <button class="btn-open-modal" onclick="openPlaceModal('${safePlaceId}')" title="Xem mô tả và địa chỉ đầy đủ">
                        <i class="fa-solid fa-circle-info"></i> <span>Xem chi tiết</span>
                    </button>
                    <a href="https://www.google.com/maps/search/?api=1&query=${mapsQuery}" target="_blank" rel="noopener noreferrer" class="btn-maps" title="Chỉ đường Google Maps">
                        <i class="fa-solid fa-location-arrow"></i> <span>Chỉ đường</span>
                    </a>
                    <button class="btn-copy-addr" onclick="copyPlaceAddress('${safePlaceId}', event)" title="Sao chép địa chỉ">
                        <i class="fa-regular fa-copy"></i>
                    </button>
                </div>
            </div>
            `;
        }).join('') + `</div>`;
    }

    const formattedReply = renderMarkdown(text.replace(/\s*\(hn_loc_\d+\)|\bhn_loc_\d+\b/gi, ''));
    const timeStr = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });

    msgDiv.innerHTML = `
        <div class="bot-icon"><i class="fa-solid fa-robot"></i></div>
        <div class="message-body">
            <div class="message-content">
                <div class="bot-text-body">${formattedReply}</div>
                ${gridHTML}
                <div class="bot-action-bar">
                    <div class="bot-action-left">
                        <button class="btn-copy-msg" onclick="copyBotMessage(this)" title="Sao chép lời tư vấn">
                            <i class="fa-regular fa-copy"></i> <span>Sao chép</span>
                        </button>
                        <span class="bot-model-tag"><i class="fa-solid fa-sparkles"></i> Gemini AI Active</span>
                    </div>
                    <span class="msg-timestamp">${timeStr}</span>
                </div>
            </div>
        </div>
    `;

    chatMessages.appendChild(msgDiv);
    scrollToBottom();

    if (saveToSession && currentChatId) {
        const session = chatSessions.find(s => s.id === currentChatId);
        if (session) {
            session.messages.push({ sender: 'bot', text: text, places: places });
            saveChatsToStorage();
        }
    }
}

// ==========================================================================
// 7. LOADING SKELETON
// ==========================================================================
function showSkeletonLoading() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    removeSkeletonLoading();

    const skelDiv = document.createElement('div');
    skelDiv.id = 'bot-skeleton-loader';
    skelDiv.className = 'message bot-message skeleton-message';
    skelDiv.innerHTML = `
        <div class="bot-icon"><i class="fa-solid fa-robot"></i></div>
        <div class="message-body">
            <div class="message-content">
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                    <em class="typing-status-label">Đang tìm địa điểm phù hợp...</em>
                </div>
            </div>
        </div>
    `;
    chatMessages.appendChild(skelDiv);
    scrollToBottom();
}

function removeSkeletonLoading() {
    const skel = document.getElementById('bot-skeleton-loader');
    if (skel) skel.remove();
}

function scrollToBottom() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages) {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }
}

function initScrollToBottom() {
    const chatMessages = document.getElementById('chat-messages');
    const scrollBtn = document.getElementById('scroll-bottom-btn');
    if (!chatMessages || !scrollBtn) return;

    chatMessages.addEventListener('scroll', () => {
        const diff = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight;
        if (diff > 120) {
            scrollBtn.classList.add('visible');
        } else {
            scrollBtn.classList.remove('visible');
        }
    });

    scrollBtn.addEventListener('click', () => {
        chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
    });
}

// ==========================================================================
// 8. MODAL CHI TIẾT ĐỊA ĐIỂM
// ==========================================================================
function initModalDOM() {
    if (document.getElementById('place-modal-overlay')) return;

    const modalHTML = `
        <div id="place-modal-overlay" class="modal-overlay" onclick="handleOverlayClick(event)">
            <div class="modal-container">
                <div class="modal-header">
                    <div>
                        <span id="modal-category" class="badge-tag">Danh mục</span>
                        <h3 id="modal-title">Tên địa điểm</h3>
                    </div>
                    <button class="modal-close-btn" onclick="closePlaceModal()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="modal-address-bar">
                        <i class="fa-solid fa-location-dot"></i>
                        <span id="modal-address">--</span>
                    </div>

                    <div class="modal-specs-grid">
                        <div class="spec-item">
                            <i class="fa-regular fa-clock"></i>
                            <div class="spec-content">
                                <span class="spec-label">Giờ mở cửa</span>
                                <span id="modal-hours" class="spec-value">--</span>
                            </div>
                        </div>
                        <div class="spec-item">
                            <i class="fa-solid fa-ticket"></i>
                            <div class="spec-content">
                                <span class="spec-label">Mức giá / Vé</span>
                                <span id="modal-price" class="spec-value">--</span>
                            </div>
                        </div>
                        <div class="spec-item">
                            <i class="fa-solid fa-users"></i>
                            <div class="spec-content">
                                <span class="spec-label">Phù hợp</span>
                                <span id="modal-suitable" class="spec-value">--</span>
                            </div>
                        </div>
                        <div class="spec-item">
                            <i class="fa-solid fa-cloud-sun"></i>
                            <div class="spec-content">
                                <span class="spec-label">Không gian</span>
                                <span id="modal-weather" class="spec-value">--</span>
                            </div>
                        </div>
                    </div>

                    <div class="modal-desc-box">
                        <h4><i class="fa-solid fa-circle-info"></i> Mô tả chi tiết & Trải nghiệm</h4>
                        <p id="modal-description">--</p>
                    </div>
                </div>
                <div class="modal-footer">
                    <div class="modal-footer-actions">
                        <a id="modal-maps-btn" href="#" target="_blank" rel="noopener noreferrer" class="btn-modal-maps">
                            <i class="fa-solid fa-location-arrow"></i> <span>Chỉ đường Google Maps</span>
                        </a>
                        <button class="btn-modal-copy" onclick="copyCurrentModalAddress()">
                            <i class="fa-regular fa-copy"></i> <span>Sao chép địa chỉ</span>
                        </button>
                    </div>
                    <button class="btn-secondary" onclick="closePlaceModal()">Đóng cửa sổ</button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
}

function openPlaceModal(placeId) {
    const place = placesDataStore.get(placeId);
    if (!place) return;

    currentModalPlace = place;

    const catBadge = document.getElementById('modal-category');
    if (catBadge) {
        catBadge.innerText = place.category || 'Địa điểm';
        catBadge.className = `badge-tag ${place.category_code || 'an-uong'}`;
    }

    const setField = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val;
    };

    setField('modal-title', place.name || '');
    setField('modal-address', place.address || `Quận ${place.district || 'Hà Nội'}`);
    setField('modal-hours', place.opening_hours || '08:00 – 22:00');
    setField('modal-price', place.price_range || 'Tham khảo');
    setField('modal-suitable', place.suitable_for || 'Tất cả đối tượng');
    setField('modal-weather', place.weather_fit || 'Trong nhà');
    setField('modal-description', place.description || 'Chưa có thông tin mô tả chi tiết cho địa điểm này.');

    const mapsBtn = document.getElementById('modal-maps-btn');
    if (mapsBtn) {
        const queryStr = encodeURIComponent((place.name || '') + ' ' + (place.address || (place.district + ' Hà Nội')));
        mapsBtn.href = `https://www.google.com/maps/search/?api=1&query=${queryStr}`;
    }

    const overlay = document.getElementById('place-modal-overlay');
    if (overlay) {
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
}

function closePlaceModal() {
    const overlay = document.getElementById('place-modal-overlay');
    if (overlay) {
        overlay.classList.remove('active');
        document.body.style.overflow = '';
    }
}

function handleOverlayClick(event) {
    if (event.target.id === 'place-modal-overlay') {
        closePlaceModal();
    }
}

function copyToClipboard(text, successMsg) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(successMsg);
        }).catch(() => fallbackCopy(text, successMsg));
    } else {
        fallbackCopy(text, successMsg);
    }
}

function fallbackCopy(text, successMsg) {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.select();
    try {
        document.execCommand('copy');
        showToast(successMsg);
    } catch (e) {
        showToast("Không thể sao chép tự động trên trình duyệt này.");
    }
    document.body.removeChild(area);
}

function copyCurrentModalAddress() {
    if (!currentModalPlace) return;
    const addr = currentModalPlace.address || `${currentModalPlace.name}, Hà Nội`;
    copyToClipboard(addr, `Đã sao chép: ${currentModalPlace.name}`);
}

function copyPlaceAddress(placeId, event) {
    if (event) event.stopPropagation();
    const place = placesDataStore.get(placeId);
    if (!place) return;
    const addr = place.address || `${place.name}, Hà Nội`;
    copyToClipboard(addr, `Đã sao chép: ${place.name}`);
}

function copyBotMessage(btn) {
    const msgCard = btn.closest('.message-content');
    if (!msgCard) return;
    const body = msgCard.querySelector('.bot-text-body');
    const text = body ? body.innerText : '';
    copyToClipboard(text, "Đã sao chép nội dung tư vấn vào clipboard!");
}

// ==========================================================================
// 9. CONFIRM MODAL (XÓA TOÀN BỘ LỊCH SỬ)
// ==========================================================================
function initConfirmModalDOM() {
    if (document.getElementById('confirm-modal-overlay')) return;

    const confirmHTML = `
        <div id="confirm-modal-overlay" class="confirm-modal-overlay" onclick="if(event.target.id==='confirm-modal-overlay') closeConfirmModal()">
            <div class="confirm-modal-card">
                <div class="confirm-icon-wrap">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                </div>
                <h3>Xóa toàn bộ lịch sử trò chuyện?</h3>
                <p>Hành động này sẽ xóa tất cả các cuộc hội thoại đã lưu và không thể hoàn tác.</p>
                <div class="confirm-modal-actions">
                    <button class="btn-confirm-cancel" onclick="closeConfirmModal()">Hủy</button>
                    <button class="btn-confirm-danger" onclick="executeClearHistory()">Xóa vĩnh viễn</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', confirmHTML);
}

function openConfirmModal() {
    const overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.classList.add('active');
}

function closeConfirmModal() {
    const overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.classList.remove('active');
}

function executeClearHistory() {
    chatSessions = [];
    localStorage.removeItem(STORAGE_KEY);
    closeConfirmModal();
    startNewChat(true);
    showToast("Đã xóa toàn bộ lịch sử trò chuyện.");
}

// ==========================================================================
// 10. TIỆN ÍCH HỖ TRỢ (MARKDOWN, ESCAPE, TOAST)
// ==========================================================================
function renderMarkdown(md) {
    if (!md) return '';
    let html = escapeHTML(md);

    // Headers
    html = html.replace(/^### (.*$)/gim, '<h4 class="md-h4">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 class="md-h3">$1</h3>');

    // Bold & Italic & Code
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Lists: convert bullet items
    html = html.replace(/^\s*[-*]\s+(.*$)/gim, '<li class="md-li">$1</li>');

    // Group consecutive list items into <ul>
    html = html.replace(/((?:<li class="md-li">.*?<\/li>\s*)+)/g, '<ul class="md-ul">$1</ul>');

    // Format paragraphs by double newline
    const blocks = html.split(/\n{2,}/);
    return blocks.map(block => {
        block = block.trim();
        if (!block) return '';
        if (block.startsWith('<h') || block.startsWith('<ul') || block.startsWith('<ol') || block.startsWith('<blockquote')) {
            return block;
        }
        return '<p>' + block.replace(/\n/g, '<br>') + '</p>';
    }).join('\n');
}

const VIETNAMESE_COMPOUND_REGEX = new RegExp(
    '(^|[^\\p{L}\\p{N}])(' +
    [
        'hai bà trưng', 'nam từ liêm', 'bắc từ liêm', 'quốc tử giám', 'hồ điều hòa',
        'khu du lịch', 'khu sinh thái', 'vườn bách thảo',
        'hà nội', 'long biên', 'gia lâm', 'cầu giấy', 'thanh xuân', 'hoàn kiếm',
        'đống đa', 'ba đình', 'tây hồ', 'hoàng mai', 'hà đông', 'đông anh',
        'sóc sơn', 'sơn tây', 'thạch thất', 'quốc oai', 'hoài đức', 'đan phượng',
        'thanh trì', 'thường tín', 'chương mỹ', 'ba vì', 'mỹ đức',
        'hồ tây', 'hồ gươm', 'vĩnh tuy', 'bát tràng', 'văn miếu', 'phố cổ', 'việt nam',
        'du lịch', 'sinh thái', 'thu nhỏ', 'vỉa hè', 'bình dân', 'giá rẻ',
        'bún đậu', 'bún chả', 'bún bò', 'phở bò', 'phở gà', 'cà phê', 'trà sữa',
        'trà chanh', 'quán ăn', 'quán nước', 'nhà hàng', 'ẩm thực', 'công viên',
        'vui chơi', 'giải trí', 'cắm trại', 'dã ngoại', 'phim trường', 'bảo tàng',
        'di tích', 'lịch sử', 'tâm linh', 'nghệ thuật', 'truyền thống', 'thể thao',
        'trong nhà', 'ngoài trời', 'sân thượng', 'ban công', 'sân vườn', 'phong cách',
        'cổ điển', 'hiện đại', 'lãng mạn', 'yên tĩnh', 'trung tâm', 'thương mại',
        'văn hóa', 'chụp ảnh', 'tham quan', 'bãi bồi', 'vườn nhãn', 'tuyệt đẹp',
        'giữa lòng', 'trời âu', 'địa điểm', 'không gian', 'hoàng hôn'
    ].join('|') +
    ')(?=[^\\p{L}\\p{N}]|$)',
    'giu'
);

/**
 * Giữ các từ ghép / địa danh tiếng Việt 2-3 âm tiết trên cùng một dòng
 * bằng khoảng trắng không ngắt (\u00A0) kết hợp text-wrap: balance.
 */
function formatBalancedCardTitle(name) {
    if (!name) return '';
    return String(name).replace(VIETNAMESE_COMPOUND_REGEX, (_, prefix, phrase) => {
        return prefix + phrase.replace(/\s+/g, '\u00A0');
    });
}

/**
 * Rút gọn nhãn phân loại xuống tối đa 2-3 chữ gọn gàng cho thẻ gợi ý.
 */
function formatShortCategory(rawCat, catCode) {
    const text = (rawCat || '').trim();
    if (!text) {
        const fallbackByCode = {
            'ca-phe': 'Quán nước',
            'an-uong': 'Quán ăn',
            'di-tich': 'Di tích',
            'tam-linh': 'Tâm linh',
            'ngoai-troi': 'Ngoài trời',
            'giai-tri': 'Giải trí',
            'the-thao': 'Thể thao',
        };
        return fallbackByCode[catCode] || 'Địa điểm';
    }
    const rules = [
        [/^quán nước/i, 'Quán nước'],
        [/^quán ăn/i, 'Quán ăn'],
        [/tâm linh/i, 'Tâm linh'],
        [/^cắm trại/i, 'Cắm trại'],
        [/^rạp chiếu phim/i, 'Rạp phim'],
        [/^trung tâm thương mại/i, 'TTTM'],
        [/^bảo tàng/i, 'Bảo tàng'],
        [/^công viên nước/i, 'Công viên nước'],
        [/^công viên/i, 'Công viên'],
        [/^hồ điều hòa/i, 'Hồ điều hòa'],
        [/sinh thái/i, 'Khu sinh thái'],
        [/^khu vui chơi/i, 'Khu vui chơi'],
        [/^thủy cung/i, 'Thủy cung'],
        [/^vườn thú/i, 'Vườn thú'],
        [/^chợ đêm/i, 'Chợ đêm'],
        [/^chợ truyền thống/i, 'Chợ truyền thống'],
        [/^phố đi bộ/i, 'Phố đi bộ'],
        [/^làng cổ/i, 'Làng cổ'],
        [/^làng hoa/i, 'Làng hoa'],
        [/^làng nghề/i, 'Làng nghề'],
        [/^di tích|^di sản/i, 'Di tích'],
        [/^danh thắng/i, 'Danh thắng'],
        [/^công trình kiến trúc|^kiến trúc di sản/i, 'Kiến trúc'],
        [/^nghệ thuật/i, 'Nghệ thuật'],
        [/^triển lãm/i, 'Triển lãm'],
        [/^thể thao/i, 'Thể thao'],
        [/sáng tạo/i, 'Sáng tạo'],
        [/^giải trí/i, 'Giải trí'],
        [/check-in|chụp ảnh/i, 'Check-in'],
        [/^cảnh quan|^tọa độ ngắm cảnh|^ngắm cảnh|^đường dạo/i, 'Cảnh quan'],
        [/văn hóa/i, 'Văn hóa'],
    ];
    for (const [pattern, label] of rules) {
        if (pattern.test(text)) return label;
    }
    const primary = text.split('/')[0].trim();
    const words = primary.split(/\s+/);
    return words.length > 3 ? words.slice(0, 3).join(' ') : primary;
}

/**
 * Chuẩn hóa nhãn thời tiết/không gian ngắn gọn trên 1 dòng.
 */
function formatWeatherBadge(rawWeather) {
    const w = (rawWeather || 'Trong nhà').trim();
    if (w.includes('/')) {
        return 'Trong & Ngoài trời';
    }
    return w;
}

function escapeHTML(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function decodeHTMLEntities(str) {
    if (!str) return '';
    const txt = document.createElement('textarea');
    txt.innerHTML = str;
    return txt.value;
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast-bubble';
    toast.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>${escapeHTML(message)}</span>`;

    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 250);
    }, 2800);
}
