type ModelLike = {
  id: string;
  label?: string;
  source?: string;
  profile?: string | null;
};

type TranslateKey =
  | 'model_profile_default'
  | 'model_profile_standard_chat'
  | 'model_profile_flagship_reasoning'
  | 'model_profile_vision_chat'
  | 'model_profile_economy_chat'
  | 'model_profile_coding'
  | 'model_profile_deep_reasoning'
  | 'model_profile_long_context_cn'
  | 'model_profile_consolidation_internal'
  | 'model_source_runtime'
  | 'model_source_builtin';

type TranslateFn = (key: TranslateKey) => string;

const PROFILE_LABEL_KEYS: Record<string, string> = {
  standard_chat: 'model_profile_standard_chat',
  flagship_reasoning: 'model_profile_flagship_reasoning',
  vision_chat: 'model_profile_vision_chat',
  economy_chat: 'model_profile_economy_chat',
  coding: 'model_profile_coding',
  deep_reasoning: 'model_profile_deep_reasoning',
  long_context_cn: 'model_profile_long_context_cn',
  consolidation_internal: 'model_profile_consolidation_internal',
};

function humanModelName(model: ModelLike): string {
  return model.label?.trim() || model.id.split('/').pop() || model.id;
}

export function profileLabel(profile: string | null | undefined, t: TranslateFn): string {
  if (!profile) return t('model_profile_default');
  const key = PROFILE_LABEL_KEYS[profile] as TranslateKey | undefined;
  return key ? t(key) : profile;
}

export function modelOptionLabel(model: ModelLike, t: TranslateFn): string {
  return humanModelName(model);
}

export function modelMetaLabel(model: ModelLike | null | undefined, t: TranslateFn): string {
  if (!model) return '';
  if (model.source === 'runtime-policy') {
    return `${t('model_source_runtime')} · ${profileLabel(model.profile, t)}`;
  }
  return t('model_source_builtin');
}
