const INTERNAL_SKILL_SECURITY_PATTERN =
  /(?:[a-z]+(?:[._-][a-z0-9]+){1,}|[A-Z][A-Z0-9_]+|api[_\s-]?key|base[_\s-]?url|authorization|bearer|token|secret|env=|env_refs|\/api\/|[{}[\]"`])/i;

const RISK_LEVEL_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '严重',
};

const RUNTIME_GATE_LABELS: Record<string, string> = {
  allow_controlled_prompt: '允许受控提示运行',
  block_high_risk_permission: '已拦截高风险权限',
  block_scripted_execution: '已拦截脚本执行',
  reference_only: '仅可查看',
};

const OPERATION_LABELS: Record<string, string> = {
  'permissions.invalid_shape': '权限声明格式异常',
  'script_policy.has_scripts': '包含脚本',
  'script.execute': '运行脚本',
  network: '访问网络',
  'files.write': '写入本机文件',
  builtin_skill_runtime: '内置 Skill 运行',
  controlled_prompt_template_render: '渲染受控提示',
  audit_append: '追加审计记录',
  manifest_inspection: '查看清单',
  approval_request: '发起授权确认',
  rollback: '回档',
};

const SANDBOX_CONTROL_LABELS: Record<string, string> = {
  argv_allowlist_no_shell: '固定启动参数且不经过命令行解释器',
  fixed_working_directory_under_skill_root: '固定在 Skill 目录内运行',
  environment_allowlist_without_secrets: '环境变量白名单且不包含密钥',
  read_roots_allowlist: '只读目录白名单',
  write_roots_allowlist: '写入目录白名单',
  network_deny_by_default: '默认禁止网络访问',
  network_allowlist_with_timeout: '网络白名单和超时限制',
  wall_clock_timeout: '运行超时限制',
  stdout_stderr_size_limits: '输出大小限制',
  append_only_audit: '只追加审计记录',
  rollback_snapshot_before_write: '写入前创建回档',
};

function isInternalSkillSecurityText(value: string): boolean {
  return INTERNAL_SKILL_SECURITY_PATTERN.test(value.trim());
}

function formatKnownOrGeneric(
  value: string,
  labels: Record<string, string>,
  genericPrefix: string,
  index: number,
): string {
  const normalized = value.trim();
  if (!normalized) return `${genericPrefix} ${index + 1}`;
  return labels[normalized] ?? `${genericPrefix} ${index + 1}`;
}

/**
 * Converts machine-readable Skill security levels into product copy.
 *
 * Input: raw backend enum-like string. Output: bounded Chinese label.
 */
export function formatSkillRiskLevel(value: string): string {
  return RISK_LEVEL_LABELS[value.trim().toLowerCase()] ?? '待评估';
}

/**
 * Converts the runtime gate decision into a user-facing Chinese sentence.
 *
 * Input: raw backend gate id. Output: bounded Chinese label.
 */
export function formatSkillRuntimeGate(value: string): string {
  return RUNTIME_GATE_LABELS[value.trim().toLowerCase()] ?? '已按当前安全策略处理';
}

/**
 * Converts operation/control ids into a comma-separated Chinese list.
 *
 * Input: backend operation ids. Output: Chinese labels; unknown ids are numbered.
 */
export function formatSkillSecurityList(
  values: readonly string[],
  emptyLabel: string,
  kind: 'operation' | 'sandbox',
): string {
  if (values.length === 0) return emptyLabel;
  const labels = kind === 'sandbox' ? SANDBOX_CONTROL_LABELS : OPERATION_LABELS;
  const genericPrefix = kind === 'sandbox' ? '安全控制项' : '受控操作';
  return values
    .map((value, index) => formatKnownOrGeneric(value, labels, genericPrefix, index))
    .filter((value, index, all) => all.indexOf(value) === index)
    .join('，');
}

/**
 * Converts backend policy reasons into safe Chinese UI copy.
 *
 * Input: optional backend reason. Output: null or bounded Chinese text.
 */
export function formatSkillSecurityReason(value: string | null | undefined, fallback: string): string | null {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return null;
  if (raw.toLowerCase().startsWith('enable high-risk user skill permissions')) {
    return '启用前需要确认高风险能力。';
  }
  if (raw === 'Review imported user Skill manifest permissions') {
    return '需要先检查导入 Skill 的权限声明。';
  }
  if (raw.startsWith('Invalid Skill permission declaration')) {
    return 'Skill 权限声明格式异常，当前仅可查看。';
  }
  if (raw === 'Scripted Skill execution is blocked until a separate sandbox runner is approved') {
    return '包含脚本的 Skill 已被拦截，需要独立沙箱能力后才能运行。';
  }
  if (raw === 'High-risk Skill permissions are blocked by the current runtime') {
    return '当前运行环境已拦截高风险权限。';
  }
  if (isInternalSkillSecurityText(raw)) return fallback;
  return raw.length > 160 ? fallback : raw;
}
