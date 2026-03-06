import { useEffect, useRef, useState } from 'preact/hooks';
import { messages, loadHistory, isStreaming, inputText, isLoadingHistory } from '../../stores/chat';
import { activeSessionKey } from '../../stores/sessions';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import plaintext from 'highlight.js/lib/languages/plaintext';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import 'highlight.js/styles/github-dark.css';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolDetail } from './ToolDetail';
import { t } from '../../stores/i18n';

hljs.registerLanguage('bash', bash);
hljs.registerAliases(['sh', 'shell', 'zsh'], { languageName: 'bash' });
hljs.registerLanguage('css', css);
hljs.registerLanguage('javascript', javascript);
hljs.registerAliases(['js', 'jsx', 'mjs', 'cjs'], { languageName: 'javascript' });
hljs.registerLanguage('json', json);
hljs.registerLanguage('plaintext', plaintext);
hljs.registerAliases(['text', 'txt'], { languageName: 'plaintext' });
hljs.registerLanguage('python', python);
hljs.registerAliases(['py'], { languageName: 'python' });
hljs.registerLanguage('sql', sql);
hljs.registerLanguage('typescript', typescript);
hljs.registerAliases(['ts', 'tsx'], { languageName: 'typescript' });
hljs.registerLanguage('xml', xml);
hljs.registerAliases(['html', 'svg'], { languageName: 'xml' });
hljs.registerLanguage('yaml', yaml);
hljs.registerAliases(['yml'], { languageName: 'yaml' });

(marked as any).setOptions({
  breaks: true,
  highlight: function(code: string, lang: string) {
    if ((window as any).__skipHighlight) return code;
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch (err) {}
    }
    return code; 
  }
});

DOMPurify.addHook('afterSanitizeAttributes', function(node) {
  if ('target' in node) {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
});

function renderMd(content: string, skipHighlight = false) {
  (window as any).__skipHighlight = skipHighlight;
  return DOMPurify.sanitize(marked.parse(content) as string);
}

function MsgActions({ msg }: { msg: any }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = () => {
    navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  
  const handleEdit = () => {
    inputText.value = msg.content;
    setTimeout(() => document.querySelector('textarea')?.focus(), 50);
  };

  return (
    <div style={{ position: 'absolute', top: '-14px', right: '0px', display: 'flex', gap: '6px', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '4px 8px', zIndex: 10, boxShadow: '0 2px 8px rgba(0,0,0,0.5)' }} className="msg-actions-bar">
       <button onClick={handleCopy} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '10px', cursor: 'pointer', fontFamily: 'var(--font-mono)' }} onMouseEnter={e => e.currentTarget.style.color='var(--teal)'} onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}>{copied ? t('copied') : t('copy')}</button>
       {msg.role === 'user' && <button onClick={handleEdit} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '10px', cursor: 'pointer', fontFamily: 'var(--font-mono)' }} onMouseEnter={e => e.currentTarget.style.color='var(--accent)'} onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}>{t('edit')}</button>}
    </div>
  );
}

export function MessageList() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    setShowScrollButton(!isAtBottom);
  };

  useEffect(() => {
    loadHistory();
  }, [activeSessionKey.value]);

  useEffect(() => {
    if (scrollRef.current) {
      const el = scrollRef.current;
      const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
      if (isAtBottom || !isStreaming.value || messages.value.length <= 2) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [messages.value, isStreaming.value]);

  if (isLoadingHistory.value) {
    return (
      <div style={{ flex: 1, padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
        <div class="skeleton-msg user"></div>
        <div class="skeleton-msg assistant"></div>
        <div class="skeleton-msg assistant long"></div>
      </div>
    );
  }

  if (messages.value.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', gap: '8px' }}>
        <div style={{ fontSize: '48px', opacity: 0.3 }}>💬</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '16px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--text-primary)' }}>
          <span style={{ color: 'var(--accent)', marginRight: '8px' }}>&gt;</span>
          {t('start_conversation')}
        </div>
        <div style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', opacity: 0.7, marginTop: '8px' }}>
          Session: {activeSessionKey.value}
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} onScroll={handleScroll} style={{ position: 'relative', flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {showScrollButton && (
        <button 
          onClick={() => { if(scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }}
          style={{ position: 'sticky', bottom: '20px', left: '50%', transform: 'translateX(-50%)', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '20px', padding: '6px 16px', color: 'var(--text-primary)', zIndex: 100, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}>
          {t('scroll_bottom')}
        </button>
      )}
      {messages.value.map((msg, i) => {
        const isUser = msg.role === 'user';
        return (
          <div 
            key={i} 
            class="msg-animate-in msg-wrapper"
            style={{ display: 'flex', gap: '12px', maxWidth: '800px', width: '100%', margin: '0 auto', justifyContent: isUser ? 'flex-end' : 'flex-start', position: 'relative' }}
          >
            {!isUser && (
              <div style={{ width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: '2px', background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}>
                <img src="/logo-icon.svg" style={{ width: '18px', height: '18px', objectFit: 'contain' }} alt="Bot" />
              </div>
            )}

            <div style={{ 
              position: 'relative', 
              maxWidth: '680px', 
              minWidth: 0, 
              padding: isUser ? '10px 14px' : '4px 0', 
              textAlign: 'left',
              background: isUser ? 'var(--bg-tertiary)' : 'transparent',
              border: isUser ? '1px solid var(--border)' : 'none',
              borderRadius: isUser ? '8px 8px 0 8px' : '0'
            }}>
              
              <MsgActions msg={msg} />

              {msg.thinking && <ThinkingBlock content={msg.thinking} />}

              {msg.tool_calls && msg.tool_calls.map((tool, ti) => (
                <ToolDetail key={ti} tool={tool} />
              ))}

              {msg.content ? (
                <div
                  className="msg-content markdown-body"
                  style={{ wordBreak: 'break-word', textAlign: 'left' }}
                  dangerouslySetInnerHTML={{ __html: renderMd(msg.content, isStreaming.value && i === messages.value.length - 1) }}
                />
              ) : (isStreaming.value && i === messages.value.length - 1 && !isUser) ? (
                <div class="streaming-indicator" style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 0', fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
                  <span class="pulse-dot" />
                  {msg.tool_calls && msg.tool_calls.length > 0 ? t('processing_tools') : t('generating')}
                </div>
              ) : null}
            </div>

            {isUser && (
              <div style={{ width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', fontWeight: 600, flexShrink: 0, marginTop: '4px', fontFamily: 'var(--font-mono)', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', color: 'var(--accent)' }}>
                U
              </div>
            )}

          </div>
        );
      })}
    </div>
  );
}