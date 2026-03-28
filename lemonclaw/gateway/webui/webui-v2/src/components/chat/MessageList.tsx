import { useEffect, useRef, useState } from 'preact/hooks';
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
import { marked } from 'marked';
import { activeSessionKey } from '../../stores/sessions';
import { inputText, isLoadingHistory, isLoadingMore, isStreaming, loadHistory, loadMoreHistory, hasMoreHistory, messages } from '../../stores/chat';
import { sessionTasks, summarizeTaskOperatorState, taskActionBusy, taskDetails, triggerSafeResume, triggerManualResume, triggerTaskRecheck } from '../../stores/tasks';
import type { UIBlock } from '../../models/messages';
import { t } from '../../stores/i18n';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolDetail } from './ToolDetail';
import { StructuredMessageContent } from './StructuredMessageContent';

const MOBILE_BREAKPOINT = 640;

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

let _skipHighlight = false;

(marked as any).setOptions({
  breaks: true,
  highlight: function(code: string, lang: string) {
    if (_skipHighlight) return code;
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value;
      } catch (_err) {}
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
  _skipHighlight = skipHighlight;
  return DOMPurify.sanitize(marked.parse(content) as string);
}

function MsgActions({ msg }: { msg: any }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      setCopyFailed(false);
    } catch (error) {
      try {
        const textarea = document.createElement('textarea');
        textarea.value = msg.content;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (!ok) throw error;
        setCopied(true);
        setCopyFailed(false);
      } catch (fallbackError) {
        console.error('Copy failed', fallbackError);
        setCopyFailed(true);
      }
    }
    setTimeout(() => {
      setCopied(false);
      setCopyFailed(false);
    }, 2000);
  };

  const handleEdit = () => {
    inputText.value = msg.content;
    setTimeout(() => document.querySelector('textarea')?.focus(), 50);
  };

  return (
    <div style={{ position: 'absolute', top: '-14px', right: '0px', display: 'flex', gap: '6px', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '999px', padding: '4px 8px', zIndex: 10, boxShadow: '0 8px 18px rgba(0,0,0,0.24)' }} className="msg-actions-bar">
      <button onClick={handleCopy} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '13px', cursor: 'pointer', fontFamily: 'var(--font-display)' }} onMouseEnter={e => e.currentTarget.style.color='var(--teal)'} onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}>{copied ? t('copied') : copyFailed ? 'COPY FAILED' : t('copy')}</button>
      {msg.role === 'user' && <button onClick={handleEdit} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: '13px', cursor: 'pointer', fontFamily: 'var(--font-display)' }} onMouseEnter={e => e.currentTarget.style.color='var(--accent)'} onMouseLeave={e => e.currentTarget.style.color='var(--text-secondary)'}>{t('edit')}</button>}
    </div>
  );
}

function translateOrFallback(key: string | null | undefined, fallback: string) {
  if (!key) return fallback;
  const translated = t(key as any);
  return translated === key ? fallback : translated;
}

function formatTaskDisplayState(state?: { key?: string; label?: string } | null) {
  if (!state) return 'Unknown';
  const translated = t(`task_state_${state.key}` as any);
  return translated === `task_state_${state.key}` ? (state.label || state.key || 'Unknown') : translated;
}

export function MessageList() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const updateViewport = () => {
      if (typeof window !== 'undefined') {
        setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
      }
    };

    updateViewport();
    window.addEventListener('resize', updateViewport);
    return () => window.removeEventListener('resize', updateViewport);
  }, []);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const el = scrollRef.current;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    setShowScrollButton(!isAtBottom);

    // Load more history when scrolling near the top
    if (el.scrollTop < 50 && hasMoreHistory.value && !isLoadingMore.value) {
      const prevHeight = el.scrollHeight;
      loadMoreHistory().then(() => {
        // Wait for DOM update before restoring scroll position
        requestAnimationFrame(() => {
          if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight - prevHeight;
          }
        });
      });
    }
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
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '15px', fontFamily: 'var(--font-ui)' }}>{t('loading_chat_history')}</div>
        <div class="skeleton-msg user"></div>
        <div class="skeleton-msg assistant"></div>
        <div class="skeleton-msg assistant long"></div>
      </div>
    );
  }

  if (messages.value.length === 0) {
    const suggestions = [
      t('chat_empty_suggestion_1'),
      t('chat_empty_suggestion_2'),
      t('chat_empty_suggestion_3'),
    ];
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: isMobile ? '20px 16px' : '32px' }}>
        <div style={{ width: '100%', maxWidth: '640px', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: '24px', padding: isMobile ? '24px' : '40px', boxShadow: '0 24px 64px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.02)' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '6px 12px', borderRadius: '999px', background: 'var(--bg-primary)', border: '1px solid var(--border)', fontFamily: 'var(--font-display)', fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '20px' }}>
            <span style={{ color: 'var(--purple)' }}>◆</span>
            <span>LemonClaw Gateway</span>
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: isMobile ? '21px' : '25px', color: 'var(--text-primary)', marginBottom: '12px', lineHeight: 1.28, fontWeight: 600, letterSpacing: '-0.03em' }}>
            {t('chat_empty_title')}
          </div>
          <div style={{ fontSize: '15px', color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: '32px', maxWidth: '560px', fontFamily: 'var(--font-reading)' }}>
            {t('chat_empty_desc')}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))', gap: '12px' }}>
            {suggestions.map((item) => (
              <button
                key={item}
                onClick={() => {
                  inputText.value = item;
                  requestAnimationFrame(() => {
                    const textarea = document.querySelector('textarea');
                    if (textarea instanceof HTMLTextAreaElement) textarea.focus();
                  });
                }}
                style={{
                  padding: '14px 16px',
                  borderRadius: '16px',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-primary)',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-reading)',
                  fontSize: '15px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  lineHeight: 1.45,
                  minHeight: isMobile ? '56px' : '80px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                  transition: 'all 0.2s',
                  display: 'flex',
                  alignItems: 'flex-start'
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.transform = 'translateY(-2px)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.transform = 'translateY(0)' }}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={scrollRef} onScroll={handleScroll} style={{ position: 'relative', flex: 1, overflowY: 'auto', padding: isMobile ? '16px 12px 24px' : '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {showScrollButton && (
        <button
          onClick={() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }}
          style={{
            position: 'sticky',
            alignSelf: 'center',
            bottom: isMobile ? '12px' : '20px',
            maxWidth: isMobile ? 'calc(100% - 16px)' : '280px',
            width: 'fit-content',
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border)',
            borderRadius: '999px',
            padding: isMobile ? '8px 12px' : '6px 16px',
            color: 'var(--text-primary)',
            zIndex: 100,
            cursor: 'pointer',
            fontFamily: 'var(--font-ui)',
            fontSize: isMobile ? '11px' : '12px',
            lineHeight: 1.2,
            whiteSpace: 'nowrap',
            boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          }}
          title={t('scroll_bottom')}
        >
          {isMobile ? t('scroll_bottom_short') : t('scroll_bottom')}
        </button>
      )}
      {messages.value.map((msg, i) => {
        const isUser = msg.role === 'user';
        return (
          <div
            key={i}
            class="msg-animate-in msg-wrapper"
            style={{ display: 'flex', gap: isMobile ? '8px' : '12px', maxWidth: '800px', width: '100%', margin: '0 auto', justifyContent: isUser ? 'flex-end' : 'flex-start', position: 'relative' }}
          >
            {!isUser && (
              <div style={{ width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: '2px', background: 'var(--bg-tertiary)', border: '1px solid var(--border)' }}>
                <img src="/logo-icon.svg" style={{ width: '18px', height: '18px', objectFit: 'contain' }} alt="Bot" />
              </div>
            )}

            <div style={{
              position: 'relative',
              maxWidth: isMobile ? 'min(100%, calc(100vw - 72px))' : '680px',
              minWidth: 0,
              padding: isUser ? '12px 14px' : '6px 0',
              textAlign: 'left',
              background: isUser ? 'linear-gradient(180deg, rgba(255,255,255,0.03) 0%, var(--bg-tertiary) 100%)' : 'transparent',
              border: isUser ? '1px solid var(--border)' : 'none',
              borderRadius: isUser ? '16px 16px 6px 16px' : '0',
              boxShadow: isUser ? '0 10px 22px rgba(0,0,0,0.14)' : 'none',
            }}>
              <MsgActions msg={msg} />

              {(msg.blocks.filter((b) => b.type === 'thinking' || b.type === 'tool').length > 0) && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '10px' }}>
                  {msg.blocks.filter((block) => block.type === 'thinking').map((block, bi) => (
                    <ThinkingBlock key={`thinking-${i}-${bi}`} id={`thinking-${i}-${bi}`} content={(block as Extract<UIBlock, { type: 'thinking' }>).text} />
                  ))}

                  {msg.blocks.filter((block) => block.type === 'tool').map((block, bi) => (
                    <ToolDetail key={`tool-${i}-${bi}`} id={`tool-${i}-${bi}`} tool={{ state: (block as Extract<UIBlock, { type: 'tool' }>).state, detail: (block as Extract<UIBlock, { type: 'tool' }>).detail, result: (block as Extract<UIBlock, { type: 'tool' }>).result }} />
                  ))}
                </div>
              )}

              {msg.blocks.filter((block) => block.type === 'error').map((block, bi) => (
                <div key={`error-${bi}`} style={{ margin: '8px 0', border: '1px solid rgba(255, 68, 68, 0.24)', borderRadius: '10px', background: 'rgba(255, 68, 68, 0.08)', color: 'var(--error)', padding: '10px 12px', fontFamily: 'var(--font-reading)', fontSize: '14px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
                  {(block as Extract<UIBlock, { type: 'error' }>).text}
                </div>
              ))}

              {msg.blocks.some((block) => ['markdown', 'runtime_context', 'transcription', 'media'].includes(block.type)) ? (
                <StructuredMessageContent
                  content={msg.content}
                  media={msg.media || []}
                  blocks={msg.blocks}
                  renderMarkdown={(value) => renderMd(value, isStreaming.value && i === messages.value.length - 1)}
                />
              ) : (isStreaming.value && i === messages.value.length - 1 && !isUser) ? (
                <div class="streaming-indicator" style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 0', fontFamily: 'var(--font-display)', fontSize: '13px', color: 'var(--text-muted)', letterSpacing: '0.02em' }}>
                  <span class="pulse-dot" />
                  {msg.blocks.some((block) => block.type === 'tool' && (block as Extract<UIBlock, { type: 'tool' }>).state === 'running') ? t('processing_tools') : t('generating')}
                </div>
              ) : null}
            </div>

            {isUser && (
              <div style={{ width: '28px', height: '28px', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '15px', fontWeight: 600, flexShrink: 0, marginTop: '4px', fontFamily: 'var(--font-ui)', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', color: 'var(--accent)' }}>
                U
              </div>
            )}
          </div>
        );
      })}

      {sessionTasks.value.filter(t => !['completed', 'abandoned'].includes(String(t.status || ''))).map(task => {
        const detail = taskDetails.value[task.task_id];
        const busy = taskActionBusy.value[task.task_id];
        const candidate = detail?.candidate;
        const state = task.display_state;
        const operatorSummary = summarizeTaskOperatorState(task, detail);
        const summaryTitle = translateOrFallback(operatorSummary.titleKey, t('task_operator_summary_title'));
        const summaryBody = translateOrFallback(operatorSummary.bodyKey, t('task_intervention_desc'));
        const nextMoveLabel = operatorSummary.actionKey
          ? translateOrFallback(operatorSummary.actionKey, t('task_action_run_safe_resume'))
          : formatTaskDisplayState(state);
        const isResumeLive = ['resume_requested', 'resume_queued', 'resume_running'].includes(state?.key || '');
        const canRunSafeResume = Boolean(candidate?.safe_to_execute);
        const canRecheck = ['waiting', 'verifying'].includes(task.status || '') && (!candidate || candidate?.recommended_action === 'recheck');
        const showRetryDispatchCta = state?.key === 'resume_dispatch_failed' && canRunSafeResume && !isResumeLive;
        const showManualResumeCta = state?.key === 'resume_manual_only' && !isResumeLive;
        const tone = operatorSummary.tone === 'error' ? 'var(--error)' : operatorSummary.tone === 'success' ? 'var(--success)' : operatorSummary.tone === 'warning' ? 'var(--warning, #ffb84d)' : 'var(--accent)';
        const bgTone = operatorSummary.tone === 'error' ? 'rgba(255, 68, 68, 0.08)' : operatorSummary.tone === 'success' ? 'rgba(76, 175, 80, 0.08)' : operatorSummary.tone === 'warning' ? 'rgba(255, 184, 77, 0.08)' : 'rgba(124, 58, 237, 0.08)';
        const borderTone = operatorSummary.tone === 'error' ? 'rgba(255, 68, 68, 0.28)' : operatorSummary.tone === 'success' ? 'rgba(76, 175, 80, 0.28)' : operatorSummary.tone === 'warning' ? 'rgba(255, 184, 77, 0.28)' : 'rgba(124, 58, 237, 0.28)';

        if (!showRetryDispatchCta && !showManualResumeCta && !canRunSafeResume && !canRecheck && !isResumeLive) {
          return null; // Not an active intervention card
        }

        return (
          <div key={`rescue-${task.task_id}`} style={{ maxWidth: '680px', width: '100%', margin: '8px auto', border: `1px solid ${borderTone}`, background: bgTone, borderRadius: '12px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', boxShadow: '0 8px 24px rgba(0,0,0,0.1)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: tone, fontFamily: 'var(--font-ui)', fontSize: '15px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '1px' }}>
              <span>🛡️</span>
              <span>{t('task_operator_summary_title')}</span>
            </div>
            
            <div style={{ display: 'grid', gap: '4px' }}>
              <div style={{ fontSize: '17px', color: 'var(--text-primary)', lineHeight: 1.45, fontWeight: 600 }}>
                {summaryTitle}
              </div>
              <div style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.55 }}>
                {summaryBody}
              </div>
              <div style={{ fontSize: '14px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                {task.goal || t('task_intervention_desc')}
              </div>
            </div>

            <div style={{ display: 'grid', gap: '8px', padding: '10px 12px', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', border: `1px solid ${borderTone}` }}>
              <div style={{ display: 'grid', gap: '4px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  {t('task_operator_summary_current_state')}
                </div>
                <div style={{ fontSize: '14px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                  {formatTaskDisplayState(state)}
                </div>
              </div>
              <div style={{ display: 'grid', gap: '4px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-ui)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  {t('task_operator_summary_next_action')}
                </div>
                <div style={{ fontSize: '14px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
                  {nextMoveLabel}
                </div>
              </div>
              {(showRetryDispatchCta || showManualResumeCta) && (
                <div style={{ fontSize: '13px', color: tone, fontFamily: 'var(--font-ui)', lineHeight: 1.45 }}>
                  {showRetryDispatchCta ? t('task_operator_cta_resume_dispatch_failed') : t('task_operator_cta_manual_resume_only')}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '4px' }}>
              {showManualResumeCta && (
                <button
                  onClick={() => triggerManualResume(task.task_id)}
                  disabled={!!busy}
                  style={{ padding: '8px 16px', background: 'transparent', border: `1px solid ${tone}`, borderRadius: '8px', color: tone, fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: busy ? 'wait' : 'pointer', fontWeight: 600, opacity: busy ? 0.7 : 1, transition: 'all 0.2s' }}
                  onMouseEnter={e => e.currentTarget.style.background = borderTone}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  {busy === 'manual_resume' ? t('task_action_running') : t('task_action_queue_manual_resume')}
                </button>
              )}
              {canRunSafeResume && !isResumeLive && (
                <button
                  onClick={() => triggerSafeResume(task.task_id)}
                  disabled={!!busy}
                  style={{ padding: '8px 16px', background: tone, border: `1px solid ${tone}`, borderRadius: '8px', color: '#fff', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: busy ? 'wait' : 'pointer', fontWeight: 600, opacity: busy ? 0.7 : 1, transition: 'all 0.2s', boxShadow: `0 4px 12px ${borderTone}` }}
                  onMouseEnter={e => e.currentTarget.style.filter = 'brightness(1.1)'}
                  onMouseLeave={e => e.currentTarget.style.filter = 'none'}
                >
                  {busy === 'resume' ? t('task_action_running') : showRetryDispatchCta ? t('task_action_retry_resume_dispatch') : t('task_action_run_safe_resume')}
                </button>
              )}
              {canRecheck && !canRunSafeResume && !isResumeLive && (
                <button
                  onClick={() => triggerTaskRecheck(task.task_id)}
                  disabled={!!busy}
                  style={{ padding: '8px 16px', background: 'transparent', border: `1px solid var(--teal)`, borderRadius: '8px', color: 'var(--teal)', fontFamily: 'var(--font-ui)', fontSize: '15px', cursor: busy ? 'wait' : 'pointer', fontWeight: 600, opacity: busy ? 0.7 : 1, transition: 'all 0.2s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(45, 212, 191, 0.1)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  {busy === 'recheck' ? t('task_action_running') : t('task_action_recheck')}
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
