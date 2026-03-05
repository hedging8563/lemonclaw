import { signal } from '@preact/signals';

const DICT = {
  en: {
    new_chat: '+ NEW',
    sessions: 'SESSIONS',
    activity: 'ACTIVITY',
    settings: 'GLOBAL SETTINGS',
    logout: 'LOGOUT',
    export: 'EXPORT',
    export_md: 'Export Markdown',
    export_json: 'Export JSON',
    sp_clear: 'Clear',
    sp_save: 'Save',
    sp_placeholder: 'System Prompt Override for this session...',
    type_message: 'Type a message or drop files...',
    send: 'SEND',
    stop: 'STOP',
    start_conversation: 'START A CONVERSATION',
    copy: 'COPY',
    edit: 'EDIT',
    copied: 'COPIED',
    star_idle: 'IDLE',
    star_writing: 'WRITING',
    star_executing: 'EXECUTING',
    star_error: 'ERROR',
    tab_providers: 'Providers',
    tab_agents: 'Agents',
    tab_channels: 'Channels',
    tab_tools: 'Tools',
    tab_skills: 'Skills',
    settings_title: 'GLOBAL_SETTINGS',
    settings_desc: 'Manage global configuration parameters across all agents.',
    btn_cancel: 'CANCEL',
    btn_save_apply: 'SAVE & APPLY',
    unsaved_changes: 'unsaved changes',
    loading: 'Loading...',
    loading_configs: 'Loading configs...',
    install: 'INSTALL',
    installing: 'INSTALLING...',
    enabled: 'ENABLED',
    no_activity: 'No activity found',
    no_memory: 'No memory found',
    no_plans: 'No active plans or agents',
    memo_yesterday: 'Yesterday',
    memo_today: 'Today',
    new_chat_fallback: 'New Chat'
  },
  zh: {
    new_chat: '+ 新建',
    sessions: '会话列表',
    activity: '活动流',
    settings: '全局设置',
    logout: '注销退出',
    export: '导出会话',
    export_md: '导出 Markdown',
    export_json: '导出 JSON',
    sp_clear: '清除',
    sp_save: '保存',
    sp_placeholder: '为当前会话覆盖全局 System Prompt...',
    type_message: '输入消息，或拖拽文件...',
    send: '发送',
    stop: '停止',
    start_conversation: '开始新的对话',
    copy: '复制',
    edit: '编辑',
    copied: '已复制',
    star_idle: '待机',
    star_writing: '输出中',
    star_executing: '执行中',
    star_error: '异常',
    tab_providers: '大模型密钥',
    tab_agents: '全局参数',
    tab_channels: '通信渠道',
    tab_tools: '工具沙箱',
    tab_skills: '技能商店',
    settings_title: '全局系统设置',
    settings_desc: '管理跨所有智能体的全局配置参数。',
    btn_cancel: '取消',
    btn_save_apply: '保存并重启',
    unsaved_changes: '个未保存的更改',
    loading: '加载中...',
    loading_configs: '配置读取中...',
    install: '安装插件',
    installing: '安装中...',
    enabled: '已启用',
    no_activity: '暂无外部消息',
    no_memory: '暂无记忆实体',
    no_plans: '当前无任务执行',
    memo_yesterday: '昨日摘要',
    memo_today: '今日日志',
    new_chat_fallback: '新对话'
  }
};

type Lang = 'en' | 'zh';
const initialLang = (localStorage.getItem('lc_lang') as Lang) || 'en';
export const lang = signal<Lang>(initialLang);

export function t(key: keyof typeof DICT['en']) {
  return DICT[lang.value][key] || key;
}

export function toggleLang() {
  const newLang = lang.value === 'en' ? 'zh' : 'en';
  lang.value = newLang;
  localStorage.setItem('lc_lang', newLang);
}