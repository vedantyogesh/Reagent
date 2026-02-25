/**
 * Ions Energy Chat Widget — vanilla JS, no framework, no build step.
 * Embed via: <script src="widget.js" data-api="https://your-api-url">
 *
 * Exposes: window.IonsEnergyChat.on(event, callback)
 * Events: sessionStart, messageReceived, proposalReady, escalated, sessionEnd, error
 */
(function () {
  'use strict';

  // ── Config from script tag ─────────────────────────────────────────────
  var scriptTag = document.currentScript || (function () {
    var scripts = document.getElementsByTagName('script');
    return scripts[scripts.length - 1];
  })();

  var API_BASE    = (scriptTag.getAttribute('data-api') || '').replace(/\/$/, '');
  var POSITION    = scriptTag.getAttribute('data-position') || 'bottom-right';
  var PRIMARY_CLR = scriptTag.getAttribute('data-primary-color') || '#0A84FF';

  if (!API_BASE) {
    console.error('[IonsEnergyChat] data-api attribute is required');
    return;
  }

  // ── Validation regexes (mirror server-side) ────────────────────────────
  var EMAIL_RE = /^[\w\.-]+@[\w\.-]+\.\w{2,}$/;
  var PHONE_RE = /^[6-9]\d{9}$/;

  // ── State ──────────────────────────────────────────────────────────────
  var state = {
    sessionId:     null,
    isOpen:        false,
    inputType:     'text',   // 'text' | 'contact_form'
    proposalReady: false,
    escalated:     false,
    isStreaming:   false,
  };

  // ── Event bus ──────────────────────────────────────────────────────────
  window.IonsEnergyChat = {
    _listeners: {},
    on: function (event, cb) {
      if (!this._listeners[event]) this._listeners[event] = [];
      this._listeners[event].push(cb);
    },
    emit: function (event, data) {
      (this._listeners[event] || []).forEach(function (cb) { cb(data); });
    },
  };

  // ── Inject CSS ─────────────────────────────────────────────────────────
  var css = [
    '#ie-chat-btn{position:fixed;' + _positionCss() + 'width:56px;height:56px;border-radius:50%;',
    'background:' + PRIMARY_CLR + ';border:none;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.18);',
    'display:flex;align-items:center;justify-content:center;z-index:99999;transition:transform .15s;}',
    '#ie-chat-btn:hover{transform:scale(1.08);}',
    '#ie-chat-btn svg{width:26px;height:26px;fill:white;}',

    '#ie-chat-window{position:fixed;' + _positionCss(true) + 'width:370px;height:560px;',
    'background:#fff;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,.18);',
    'display:none;flex-direction:column;z-index:99999;overflow:hidden;',
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}',
    '#ie-chat-window.ie-open{display:flex;}',

    '#ie-chat-header{background:' + PRIMARY_CLR + ';color:white;padding:14px 16px;',
    'display:flex;align-items:center;gap:10px;flex-shrink:0;}',
    '#ie-chat-header .ie-avatar{width:36px;height:36px;border-radius:50%;',
    'background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center;}',
    '#ie-chat-header .ie-avatar svg{width:20px;height:20px;fill:white;}',
    '#ie-chat-header .ie-title{font-weight:600;font-size:15px;}',
    '#ie-chat-header .ie-subtitle{font-size:11px;opacity:.8;}',
    '#ie-chat-header .ie-close{margin-left:auto;background:none;border:none;',
    'color:white;cursor:pointer;font-size:20px;line-height:1;padding:2px 4px;}',

    '#ie-messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;}',
    '.ie-msg{max-width:82%;padding:10px 13px;border-radius:14px;font-size:13.5px;line-height:1.5;word-wrap:break-word;}',
    '.ie-msg.ie-bot{background:#f0f4ff;color:#1a1a2e;border-bottom-left-radius:4px;align-self:flex-start;}',
    '.ie-msg.ie-user{background:' + PRIMARY_CLR + ';color:white;border-bottom-right-radius:4px;align-self:flex-end;}',
    '.ie-typing{display:flex;gap:4px;padding:12px 14px;}.ie-typing span{width:7px;height:7px;',
    'border-radius:50%;background:#aab;animation:ie-bounce .8s infinite ease-in-out;}',
    '.ie-typing span:nth-child(2){animation-delay:.15s;}.ie-typing span:nth-child(3){animation-delay:.3s;}',
    '@keyframes ie-bounce{0%,80%,100%{transform:scale(.6)}40%{transform:scale(1)}}',

    '#ie-input-area{padding:12px;border-top:1px solid #eee;flex-shrink:0;}',
    '#ie-text-row{display:flex;gap:8px;}',
    '#ie-text-input{flex:1;border:1.5px solid #dde;border-radius:10px;padding:9px 12px;',
    'font-size:13.5px;outline:none;resize:none;font-family:inherit;}',
    '#ie-text-input:focus{border-color:' + PRIMARY_CLR + ';}',
    '#ie-send-btn{background:' + PRIMARY_CLR + ';color:white;border:none;border-radius:10px;',
    'width:42px;cursor:pointer;font-size:18px;transition:opacity .15s;}',
    '#ie-send-btn:disabled{opacity:.4;cursor:default;}',

    '#ie-contact-form{display:none;flex-direction:column;gap:8px;}',
    '#ie-contact-form.ie-visible{display:flex;}',
    '.ie-contact-field{display:flex;flex-direction:column;gap:3px;}',
    '.ie-contact-field label{font-size:11px;font-weight:600;color:#666;text-transform:uppercase;}',
    '.ie-contact-field input{border:1.5px solid #dde;border-radius:8px;padding:8px 10px;font-size:13px;outline:none;}',
    '.ie-contact-field input:focus{border-color:' + PRIMARY_CLR + ';}',
    '.ie-contact-field input.ie-error{border-color:#e94560;}',
    '.ie-field-error{font-size:11px;color:#e94560;}',
    '#ie-contact-submit{background:' + PRIMARY_CLR + ';color:white;border:none;border-radius:8px;',
    'padding:10px;font-size:13.5px;font-weight:600;cursor:pointer;margin-top:2px;}',
    '#ie-contact-submit:hover{opacity:.9;}',

    '#ie-download-btn{display:none;width:100%;background:#16a34a;color:white;border:none;',
    'border-radius:8px;padding:10px;font-size:13.5px;font-weight:600;cursor:pointer;margin-bottom:8px;}',
    '#ie-download-btn.ie-visible{display:block;}',
    '#ie-download-btn:hover{opacity:.9;}',

    '.ie-escalated-note{font-size:12px;color:#888;text-align:center;padding:4px 0;}',
  ].join('');

  var styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ── Build DOM ──────────────────────────────────────────────────────────
  var btn = _el('button', { id: 'ie-chat-btn', 'aria-label': 'Open chat' });
  btn.innerHTML = _chatIcon();

  var win = _el('div', { id: 'ie-chat-window', role: 'dialog', 'aria-label': 'Chat' });
  win.innerHTML = [
    '<div id="ie-chat-header">',
    '  <div class="ie-avatar">' + _botIcon() + '</div>',
    '  <div><div class="ie-title">Ions Energy</div><div class="ie-subtitle">Energy Solutions Assistant</div></div>',
    '  <button class="ie-close" aria-label="Close">&#x2715;</button>',
    '</div>',
    '<div id="ie-messages"></div>',
    '<div id="ie-input-area">',
    '  <button id="ie-download-btn">&#8595; Download Proposal</button>',
    '  <div id="ie-contact-form">',
    '    <div class="ie-contact-field">',
    '      <label for="ie-email">Email</label>',
    '      <input type="email" id="ie-email" placeholder="you@example.com" autocomplete="email">',
    '      <span class="ie-field-error" id="ie-email-err"></span>',
    '    </div>',
    '    <div class="ie-contact-field">',
    '      <label for="ie-phone">Phone (Indian mobile)</label>',
    '      <input type="tel" id="ie-phone" placeholder="9876543210" autocomplete="tel">',
    '      <span class="ie-field-error" id="ie-phone-err"></span>',
    '    </div>',
    '    <span class="ie-field-error" id="ie-contact-global-err"></span>',
    '    <button id="ie-contact-submit">Submit Contact Info</button>',
    '  </div>',
    '  <div id="ie-text-row">',
    '    <textarea id="ie-text-input" rows="1" placeholder="Type a message…"></textarea>',
    '    <button id="ie-send-btn" aria-label="Send">&#10148;</button>',
    '  </div>',
    '</div>',
  ].join('');

  document.body.appendChild(btn);
  document.body.appendChild(win);

  // ── DOM refs ───────────────────────────────────────────────────────────
  var msgs          = document.getElementById('ie-messages');
  var textInput     = document.getElementById('ie-text-input');
  var sendBtn       = document.getElementById('ie-send-btn');
  var contactForm   = document.getElementById('ie-contact-form');
  var emailInput    = document.getElementById('ie-email');
  var phoneInput    = document.getElementById('ie-phone');
  var contactSubmit = document.getElementById('ie-contact-submit');
  var downloadBtn   = document.getElementById('ie-download-btn');
  var closeBtn      = win.querySelector('.ie-close');

  // ── Event listeners ────────────────────────────────────────────────────
  btn.addEventListener('click', _toggleOpen);
  closeBtn.addEventListener('click', _toggleOpen);
  sendBtn.addEventListener('click', _handleSend);
  textInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _handleSend(); }
  });
  textInput.addEventListener('input', _autoResize);
  contactSubmit.addEventListener('click', _handleContactSubmit);
  emailInput.addEventListener('blur', function () { _validateEmailField(false); });
  phoneInput.addEventListener('blur', function () { _validatePhoneField(false); });
  downloadBtn.addEventListener('click', _downloadProposal);

  // ── Open/close ─────────────────────────────────────────────────────────
  function _toggleOpen() {
    state.isOpen = !state.isOpen;
    if (state.isOpen) {
      win.classList.add('ie-open');
      btn.style.display = 'none';
      if (!state.sessionId) _startSession();
    } else {
      win.classList.remove('ie-open');
      btn.style.display = '';
    }
  }

  // ── Session start ──────────────────────────────────────────────────────
  function _startSession() {
    fetch(API_BASE + '/session/start', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.sessionId = data.session_id;
        window.IonsEnergyChat.emit('sessionStart', { session_id: data.session_id });
        _appendBotMsg('Hi! I\'m the Ions Energy assistant. How can I help you today?');
      })
      .catch(function (err) {
        _appendBotMsg('Sorry, I couldn\'t connect. Please refresh and try again.');
        window.IonsEnergyChat.emit('error', { message: err.message });
      });
  }

  // ── Send message ───────────────────────────────────────────────────────
  function _handleSend() {
    var text = textInput.value.trim();
    if (!text || state.isStreaming || state.escalated) return;
    textInput.value = '';
    _autoResize();
    _sendMessage(text);
  }

  function _sendMessage(text) {
    _appendUserMsg(text);
    _showTyping();
    state.isStreaming = true;
    sendBtn.disabled = true;

    var botBubble = null;
    var buffer = '';

    var evtSource = new EventSource(
      API_BASE + '/chat?' + new URLSearchParams({ session_id: state.sessionId, message: text }),
    );

    // Fallback: use fetch + ReadableStream for POST
    _fetchSSE(text, function onToken(token) {
      _hideTyping();
      if (!botBubble) botBubble = _appendBotMsg('');
      buffer += token;
      botBubble.textContent = buffer;
      msgs.scrollTop = msgs.scrollHeight;
    }, function onDone(payload) {
      state.isStreaming = false;
      sendBtn.disabled = false;

      window.IonsEnergyChat.emit('messageReceived', {
        message: buffer,
        flow_state: payload.flow_state,
      });

      if (payload.input_type === 'contact_form') {
        _showContactForm();
      } else {
        _showTextInput();
      }

      if (payload.proposal_ready && !state.proposalReady) {
        state.proposalReady = true;
        downloadBtn.classList.add('ie-visible');
        window.IonsEnergyChat.emit('proposalReady', { session_id: state.sessionId });
      }

      if (payload.escalated && !state.escalated) {
        state.escalated = true;
        _disableInput();
        window.IonsEnergyChat.emit('escalated', { session_id: state.sessionId });
      }
    }, function onError(err) {
      state.isStreaming = false;
      sendBtn.disabled = false;
      _hideTyping();
      _appendBotMsg('Sorry, something went wrong. Please try again.');
      window.IonsEnergyChat.emit('error', { message: err });
    });
  }

  function _fetchSSE(text, onToken, onDone, onError) {
    fetch(API_BASE + '/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, message: text }),
    }).then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buf = '';

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) return;
          buf += decoder.decode(result.value, { stream: true });
          var lines = buf.split('\n');
          buf = lines.pop();   // incomplete line stays in buffer
          lines.forEach(function (line) {
            if (!line.startsWith('data: ')) return;
            try {
              var evt = JSON.parse(line.slice(6));
              if (evt.type === 'token') onToken(evt.content);
              if (evt.type === 'done')  onDone(evt);
              if (evt.type === 'error') onError(evt.message);
            } catch (_) {}
          });
          return pump();
        });
      }
      return pump();
    }).catch(onError);
  }

  // ── Contact form ───────────────────────────────────────────────────────
  function _showContactForm() {
    contactForm.classList.add('ie-visible');
    document.getElementById('ie-text-row').style.display = 'none';
    emailInput.value = '';
    phoneInput.value = '';
    _clearContactErrors();
  }

  function _showTextInput() {
    contactForm.classList.remove('ie-visible');
    document.getElementById('ie-text-row').style.display = 'flex';
    textInput.focus();
  }

  function _validateEmailField(strict) {
    var val = emailInput.value.trim();
    if (!val) { _setFieldError(emailInput, 'ie-email-err', ''); return true; }
    var ok = EMAIL_RE.test(val);
    _setFieldError(emailInput, 'ie-email-err', ok ? '' : 'Invalid email address');
    return ok;
  }

  function _validatePhoneField(strict) {
    var val = phoneInput.value.trim();
    if (!val) { _setFieldError(phoneInput, 'ie-phone-err', ''); return true; }
    var ok = PHONE_RE.test(val);
    _setFieldError(phoneInput, 'ie-phone-err', ok ? '' : 'Enter a valid 10-digit Indian mobile number');
    return ok;
  }

  function _handleContactSubmit() {
    _clearContactErrors();
    var email = emailInput.value.trim();
    var phone = phoneInput.value.trim();

    var emailOk = !email || EMAIL_RE.test(email);
    var phoneOk = !phone || PHONE_RE.test(phone);

    if (!emailOk) _setFieldError(emailInput, 'ie-email-err', 'Invalid email address');
    if (!phoneOk) _setFieldError(phoneInput, 'ie-phone-err', 'Enter a valid 10-digit Indian mobile number');

    if (!email && !phone) {
      document.getElementById('ie-contact-global-err').textContent =
        'Please enter at least one contact — email or phone.';
      return;
    }

    if (!emailOk || !phoneOk) return;

    // Serialise for backend
    var parts = [];
    if (email) parts.push('email: ' + email);
    if (phone) parts.push('phone: ' + phone);
    var msg = parts.join(' | ');

    _showTextInput();
    _sendMessage(msg);
  }

  function _clearContactErrors() {
    document.getElementById('ie-email-err').textContent = '';
    document.getElementById('ie-phone-err').textContent = '';
    document.getElementById('ie-contact-global-err').textContent = '';
    emailInput.classList.remove('ie-error');
    phoneInput.classList.remove('ie-error');
  }

  function _setFieldError(input, errId, msg) {
    document.getElementById(errId).textContent = msg;
    if (msg) input.classList.add('ie-error');
    else input.classList.remove('ie-error');
  }

  // ── Download proposal ──────────────────────────────────────────────────
  function _downloadProposal() {
    if (!state.sessionId) return;
    window.open(API_BASE + '/proposal/download/' + state.sessionId, '_blank');
  }

  // ── Disable input (escalation) ─────────────────────────────────────────
  function _disableInput() {
    textInput.disabled = true;
    sendBtn.disabled = true;
    contactForm.classList.remove('ie-visible');
    var note = document.createElement('p');
    note.className = 'ie-escalated-note';
    note.textContent = 'Chat has ended. Our team will be in touch.';
    document.getElementById('ie-input-area').appendChild(note);
  }

  // ── Message helpers ────────────────────────────────────────────────────
  function _appendBotMsg(text) {
    var div = _el('div', { class: 'ie-msg ie-bot' });
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function _appendUserMsg(text) {
    var div = _el('div', { class: 'ie-msg ie-user' });
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function _showTyping() {
    _hideTyping();
    var div = _el('div', { id: 'ie-typing', class: 'ie-msg ie-bot ie-typing' });
    div.innerHTML = '<span></span><span></span><span></span>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function _hideTyping() {
    var t = document.getElementById('ie-typing');
    if (t) t.remove();
  }

  // ── Textarea auto-resize ───────────────────────────────────────────────
  function _autoResize() {
    textInput.style.height = 'auto';
    textInput.style.height = Math.min(textInput.scrollHeight, 100) + 'px';
  }

  // ── DOM utility ────────────────────────────────────────────────────────
  function _el(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  function _positionCss(isWindow) {
    var offset = isWindow ? '80px' : '24px';
    var base   = isWindow ? 'bottom:88px;' : 'bottom:24px;';
    if (POSITION === 'bottom-left') return base + 'left:' + offset + ';';
    return base + 'right:' + offset + ';';
  }

  function _chatIcon() {
    return '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';
  }

  function _botIcon() {
    return '<svg viewBox="0 0 24 24"><path d="M12 2a2 2 0 012 2 2 2 0 01-2 2 2 2 0 01-2-2 2 2 0 012-2m0 6c2.67 0 8 1.34 8 4v2H4v-2c0-2.66 5.33-4 8-4z"/></svg>';
  }

})();
