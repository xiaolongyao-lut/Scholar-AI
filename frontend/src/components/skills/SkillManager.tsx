/**
 * SkillManager component.
 *
 * Displays builtin vs user skills in separate sections,
 * with import, enable/disable, test-run, and audit capabilities.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Layers, Shield, Play, Ban, CheckCircle2, AlertTriangle,
  History, Download, Plus, ChevronRight, X, Loader2,
  Lock, Terminal, Cpu, Database, Eye, ExternalLink,
  Trash2, RotateCcw, ClipboardCheck, Clock3, type LucideIcon,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { Modal, ModalBody, ModalFooter, ModalHeader } from '@/components/ui/Modal';
import CredentialPicker from '@/components/settings/credentials/CredentialPicker';
import {
  formatDynamicConfigFieldLabel,
  formatDynamicDescription,
  formatDynamicOptionLabel,
  getDynamicConfigManualEntryHint,
} from '@/components/settings/dynamicConfigDisplay';
import {
  formatSkillRiskLevel,
  formatSkillRuntimeGate,
  formatSkillSecurityList,
  formatSkillSecurityReason,
} from './skillSecurityDisplay';
import type {
  PermissionKey,
  SkillDescriptor,
  SkillAuditEvent,
  SkillApprovalRequest,
  SkillSecurityAssessment,
  SkillUninstallResult,
  SkillConfigField,
  SkillConfigOption,
  SkillRequiredCredential,
  SkillRuntimeSettings,
} from '@/types/skills';
import type { SkillTestRunResult } from '@/types/skills';
import { HIGH_RISK_PERMISSIONS } from '@/types/skills';
import * as skillApi from '@/services/skillApi';

interface SkillManagerProps {
  embedded?: boolean;
}

type Translate = (key: string, params?: Record<string, string | number>) => string;

interface SkillTestResultView {
  tone: 'success' | 'error';
  title: string;
  details: string[];
}

const truncateText = (value: string, maxLength: number): string => {
  if (maxLength < 1) return '';
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
};

const SKILL_INTERNAL_TEXT_PATTERN =
  /(?:env=|env_refs|[A-Z][A-Z0-9]+_[A-Z0-9_]+|[a-z]+(?:_[a-z0-9]+){1,}|(?:capability|credential|provider|server|agent|event|job|audit|api|base|token|secret|workspace|source|material|session|tool)_[a-z0-9_]+|api[\s_-]*key|base[\s_-]*url|authorization|bearer|token|secret|password|credential|\/api\/[^\s"'<>，。；,;)]*|\/runtime\/[^\s"'<>，。；,;)]*|\/resources\/[^\s"'<>，。；,;)]*|[A-Za-z]:[\\/][^\s"'<>]*)/i;

const sanitizeSkillUserMessage = (value: unknown, fallback: string): string => {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return fallback;
  if (SKILL_INTERNAL_TEXT_PATTERN.test(raw)) return fallback;
  if ((raw.startsWith('{') && raw.endsWith('}')) || (raw.startsWith('[') && raw.endsWith(']'))) {
    return fallback;
  }
  return raw;
};

const sanitizeSkillMessageList = (values: readonly unknown[], fallback: string): string[] => {
  const sanitized = values
    .map((value) => sanitizeSkillUserMessage(value, fallback))
    .filter((value, index, all) => value && all.indexOf(value) === index);
  return sanitized.length > 0 ? sanitized : [fallback];
};

const formatSkillError = (error: unknown, fallback: string): string => (
  sanitizeSkillUserMessage(error instanceof Error ? error.message : typeof error === 'string' ? error : '', fallback)
);

const readStringField = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
};

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const readStringMap = (value: unknown): Record<string, string> => {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]): Array<[string, string]> => {
      if (!key.trim() || typeof item !== 'string') return [];
      return [[key, item]];
    }),
  );
};

const readOptionalNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const readSkillConfigFields = (skill: SkillDescriptor): SkillConfigField[] => {
  const raw = skill.default_parameters.config_fields;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): SkillConfigField[] => {
    if (!isRecord(item)) return [];
    const id = readStringField(item.id);
    const label = readStringField(item.label);
    const env = readStringField(item.env);
    const type =
      item.type === 'select' || item.type === 'text' || item.type === 'number' || item.type === 'boolean'
        ? item.type
        : null;
    if (!id || !label || !env || !type) return [];
    const rawOptions = Array.isArray(item.options) ? item.options : null;
    const options = rawOptions?.flatMap((option): SkillConfigOption[] => {
      if (!isRecord(option)) return [];
      const value = readStringField(option.value);
      const optionLabel = readStringField(option.label);
      return value && optionLabel ? [{ value, label: optionLabel }] : [];
    }) ?? null;
    return [{
      id,
      label,
      env,
      type,
      default: typeof item.default === 'string' ? item.default : null,
      required: item.required === true,
      description: typeof item.description === 'string' ? item.description : '',
      options,
      min: readOptionalNumber(item.min),
      max: readOptionalNumber(item.max),
      step: readOptionalNumber(item.step),
    }];
  });
};

const readSkillRequiredCredentials = (skill: SkillDescriptor): SkillRequiredCredential[] => {
  const raw = skill.default_parameters.required_credentials;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): SkillRequiredCredential[] => {
    if (!isRecord(item)) return [];
    const id = readStringField(item.id);
    const label = readStringField(item.label);
    const env = readStringField(item.env);
    if (!id || !label || !env || item.kind !== 'api_key') return [];
    return [{
      id,
      label,
      env,
      kind: 'api_key',
      provider_hints: Array.isArray(item.provider_hints)
        ? item.provider_hints.filter((hint): hint is string => typeof hint === 'string')
        : [],
      required: item.required !== false,
      description: typeof item.description === 'string' ? item.description : '',
    }];
  });
};

const readSkillRuntimeSettings = (skill: SkillDescriptor): SkillRuntimeSettings => ({
  config_values: readStringMap(skill.default_parameters.config_values),
  credential_bindings: readStringMap(skill.default_parameters.credential_bindings),
});

const SKILL_AUDIT_EVENT_LABELS: Record<string, { label: string; hint: string }> = {
  job_created: { label: '任务已创建', hint: '系统已为一次 Skill 执行建立任务记录。' },
  capability_resolved: { label: '功能匹配完成', hint: '系统已确认要使用的 Skill、安装状态和配置状态。' },
  approval_requested: { label: '等待授权', hint: '高风险能力需要用户确认后才能继续。' },
  approval_decided: { label: '授权已处理', hint: '用户已经批准、拒绝或暂缓这次授权请求。' },
  execution_attempted: { label: '准备执行', hint: '系统准备调用 Skill 能力。' },
  execution_blocked: { label: '执行被拦截', hint: '策略、权限或安全检查阻止了这次执行。' },
  execution_started: { label: '执行已开始', hint: 'Skill 能力已经开始运行。' },
  execution_completed: { label: '执行完成', hint: 'Skill 能力执行成功并返回结果。' },
  execution_failed: { label: '执行失败', hint: 'Skill 能力执行时发生错误。' },
  artifact_generated: { label: '产物已生成', hint: 'Skill 产生了可保存或可查看的输出。' },
  error_occurred: { label: '发生错误', hint: '系统记录了一条错误事件。' },
};

const SKILL_AUDIT_SEVERITY_LABELS: Record<string, string> = {
  debug: '低级别记录',
  info: '信息',
  warning: '警告',
  error: '错误',
  critical: '严重',
};

const SKILL_AUDIT_STATUS_LABELS: Record<string, string> = {
  logged: '已记录',
  processed: '已处理',
  archived: '已归档',
};

const getSkillAuditEventMeta = (eventType: string): { label: string; hint: string } => {
  const normalized = eventType.trim().toLowerCase();
  return SKILL_AUDIT_EVENT_LABELS[normalized] ?? {
    label: '系统事件',
    hint: '这是一条尚未归类的 Skill 审计事件；技术细节已隐藏。',
  };
};

const auditRecordSize = (value: Record<string, unknown> | null | undefined): number => {
  if (!value || typeof value !== 'object') return 0;
  return Object.keys(value).length;
};

export const formatSkillAuditDescription = (
  event: SkillAuditEvent,
  meta: { label: string; hint: string } = getSkillAuditEventMeta(event.event_type),
): string => (
  sanitizeSkillUserMessage(event.description, meta.hint)
);

export const buildSkillAuditDetails = (event: SkillAuditEvent): Array<{ label: string; value: string; mono?: boolean }> => {
  const meta = getSkillAuditEventMeta(event.event_type);
  const details: Array<{ label: string; value: string; mono?: boolean }> = [
    { label: '事件类型', value: meta.label },
    { label: '说明', value: meta.hint },
    { label: '时间', value: new Date(event.timestamp).toLocaleString() },
    { label: '状态', value: SKILL_AUDIT_STATUS_LABELS[event.status ?? ''] ?? event.status ?? '已记录' },
    { label: '级别', value: SKILL_AUDIT_SEVERITY_LABELS[event.severity] ?? event.severity },
  ];

  if (event.capability_id) details.push({ label: '关联 Skill', value: '已关联到一个 Skill 能力' });
  if (event.job_id) details.push({ label: '关联任务', value: '已关联到一次本地任务' });
  if (event.session_id) details.push({ label: '关联会话', value: '已关联到一次会话' });
  if (event.user_id) details.push({ label: '用户来源', value: '已记录' });
  if (event.error_code) details.push({ label: '错误类别', value: '系统已归类' });
  if (event.error_message) {
    details.push({
      label: '错误信息',
      value: sanitizeSkillUserMessage(event.error_message, '错误详情已隐藏，避免显示内部配置或本地路径。'),
    });
  }
  const contextSize = auditRecordSize(event.context);
  if (contextSize > 0) {
    details.push({ label: '诊断上下文', value: `已记录 ${contextSize} 项内部诊断信息` });
  }
  const previousStateSize = auditRecordSize(event.previous_state);
  if (previousStateSize > 0) {
    details.push({ label: '变更前状态', value: `已记录 ${previousStateSize} 项内部状态` });
  }
  const newStateSize = auditRecordSize(event.new_state);
  if (newStateSize > 0) {
    details.push({ label: '变更后状态', value: `已记录 ${newStateSize} 项内部状态` });
  }
  return details;
};

const buildImportErrorDetails = (error: unknown, t: Translate): SkillTestResultView => {
  if (error instanceof skillApi.SkillApiError) {
    switch (error.errorCode) {
      case 'UNSUPPORTED_SOURCE_PATH':
      case 'EMPTY_SOURCE_PATH':
        return {
          tone: 'error',
          title: t('skills.import_source_invalid_title'),
          details: [t('skills.import_source_invalid_hint')],
        };
      case 'INVALID_ZIP_ARCHIVE':
        return {
          tone: 'error',
          title: t('skills.import_zip_invalid_title'),
          details: [t('skills.import_zip_invalid_hint')],
        };
      case 'UNSAFE_ARCHIVE_ENTRY':
        return {
          tone: 'error',
          title: t('skills.import_zip_unsafe_title'),
          details: [t('skills.import_zip_unsafe_hint')],
        };
      case 'MISSING_SKILL_MD':
        return {
          tone: 'error',
          title: t('skills.import_manifest_missing_title'),
          details: [t('skills.import_manifest_missing_hint')],
        };
      case 'INVALID_MANIFEST':
        return {
          tone: 'error',
          title: t('skills.import_manifest_invalid_title'),
          details: sanitizeSkillMessageList(
            error.errors.length > 0 ? error.errors : [error.message],
            t('skills.import_manifest_invalid_title'),
          ),
        };
      default:
        return {
          tone: 'error',
          title: t('skills.import_failed_title'),
          details: sanitizeSkillMessageList(
            error.errors.length > 0 ? error.errors : [error.message],
            t('skills.import_failed_title'),
          ),
        };
    }
  }

  return {
    tone: 'error',
    title: t('skills.import_failed_title'),
    details: [formatSkillError(error, t('skills.import_failed_title'))],
  };
};

export const buildSkillTestDetails = (result: SkillTestRunResult, t: Translate): string[] => {
  const details: string[] = [
    t('skills.test_duration', { ms: result.execution_time_ms }),
  ];
  const outputText = sanitizeSkillUserMessage(
    result.output_text,
    '测试输出已隐藏，避免显示内部配置或本地路径。',
  );
  const executionMode = readStringField(result.structured_output.execution_mode);

  if (outputText.length > 0 && outputText !== '测试输出已隐藏，避免显示内部配置或本地路径。') {
    details.unshift(t('skills.test_output', { output: truncateText(outputText, 240) }));
  } else if (result.output_text.trim().length > 0) {
    details.unshift(t('skills.test_output', { output: outputText }));
  }

  if (executionMode) {
    details.push(t('skills.test_execution_mode', {
      mode: sanitizeSkillUserMessage(executionMode, '受控运行方式'),
    }));
  }

  if (result.evidence_refs.length > 0) {
    details.push(t('skills.test_evidence_count', { count: result.evidence_refs.length }));
  }

  if (result.warnings.length > 0) {
    details.push(t('skills.test_warnings', { count: result.warnings.length }));
  }

  if (result.audit_id) {
    details.push('已记录测试审计流水。');
  }

  return details;
};

export function SkillManager({ embedded = false }: SkillManagerProps) {
  const { t } = useI18n();
  const [skills, setSkills] = useState<SkillDescriptor[]>([]);
  const [auditEvents, setAuditEvents] = useState<SkillAuditEvent[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<SkillApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvalsLoading, setApprovalsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'skills' | 'approvals' | 'audit'>('skills');
  const [importPath, setImportPath] = useState('');
  const [importing, setImporting] = useState(false);
  const [testResult, setTestResult] = useState<SkillTestResultView | null>(null);
  const [uninstallTarget, setUninstallTarget] = useState<SkillDescriptor | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<SkillDescriptor | null>(null);
  const [uninstallPreview, setUninstallPreview] = useState<SkillUninstallResult | null>(null);
  const [securityAssessments, setSecurityAssessments] = useState<Record<string, SkillSecurityAssessment>>({});
  const [securityLoadingId, setSecurityLoadingId] = useState<string | null>(null);
  const [backupPathInput, setBackupPathInput] = useState('');
  const [modalBusy, setModalBusy] = useState(false);
  const [exportingSkillId, setExportingSkillId] = useState<string | null>(null);
  const [expandedAuditEventId, setExpandedAuditEventId] = useState<string | null>(null);
  const [savingSkillSettingsId, setSavingSkillSettingsId] = useState<string | null>(null);

  const loadSkills = useCallback(async () => {
    try {
      setLoading(true);
      const [builtinSkills, importedSkills] = await Promise.all([
        skillApi.listSkills({ source: 'builtin' }),
        skillApi.listSkills({ source: 'imported' }),
      ]);
      setSkills([...importedSkills, ...builtinSkills]);
      setError(null);
    } catch (err) {
      setError(formatSkillError(err, '加载 Skill 列表失败，请稍后重试。'));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async () => {
    try {
      const events = await skillApi.getSkillAudit(undefined, 50);
      setAuditEvents(events);
    } catch {
      // Non-critical
    }
  }, []);

  const loadApprovals = useCallback(async () => {
    try {
      setApprovalsLoading(true);
      const requests = await skillApi.listPendingApprovals();
      setPendingApprovals(requests);
    } catch (err) {
      setError(formatSkillError(err, '读取卸载预览失败，请稍后重试。'));
    } finally {
      setApprovalsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  useEffect(() => {
    if (activeTab === 'audit') loadAudit();
    if (activeTab === 'approvals') loadApprovals();
  }, [activeTab, loadAudit, loadApprovals]);

  const handleImport = async () => {
    if (!importPath.trim()) return;
    setImporting(true);
    try {
      const sourcePath = importPath.trim();
      const result = await skillApi.importSkill(sourcePath);
      if (result.success) {
        setImportPath('');
        setTestResult({
          tone: 'success',
          title: t('skills.import_done', { name: result.manifest?.name ?? result.skill_id }),
          details: [
            t('skills.import_origin', { origin: result.origin || sourcePath }),
            t('skills.import_runtime_boundary'),
          ],
        });
        await loadSkills();
      }
    } catch (err) {
      setTestResult(buildImportErrorDetails(err, t));
    } finally {
      setImporting(false);
    }
  };

  const handleToggle = async (skill: SkillDescriptor) => {
    try {
      if (skill.disabled_reason) {
        await skillApi.enableSkill(skill.id);
      } else {
        await skillApi.disableSkill(skill.id);
      }
      await loadSkills();
    } catch (err) {
      if (err instanceof skillApi.SkillApiError && err.status === 409) {
        setTestResult({
          tone: 'error',
          title: t('skills.enable_requires_approval'),
          details: [formatSkillError(err, t('skills.enable_requires_approval'))],
        });
        setActiveTab('approvals');
        await loadApprovals();
        return;
      }
      setError(formatSkillError(err, '切换 Skill 状态失败，请稍后重试。'));
    }
  };

  const handleTestRun = async (skillId: string) => {
    try {
      const result = await skillApi.testRunSkill(skillId);
      setTestResult({
        tone: result.status === 'success' ? 'success' : 'error',
        title: t('skills.test_result_title', { status: result.status }),
        details: buildSkillTestDetails(result, t),
      });
    } catch (err) {
      setTestResult({
        tone: 'error',
        title: t('skills.test_error_title'),
        details: [formatSkillError(err, t('skills.test_error_title'))],
      });
    }
  };

  const handleInspectSecurity = async (skill: SkillDescriptor) => {
    if (securityAssessments[skill.id]) {
      setSecurityAssessments(({ [skill.id]: _removed, ...rest }) => rest);
      return;
    }

    setSecurityLoadingId(skill.id);
    try {
      const assessment = await skillApi.getSkillSecurity(skill.id);
      setSecurityAssessments(prev => ({
        ...prev,
        [skill.id]: assessment,
      }));
    } catch (err) {
      setError(formatSkillError(err, '加载授权请求失败，请稍后重试。'));
    } finally {
      setSecurityLoadingId(null);
    }
  };

  const handleApprovalDecision = async (request: SkillApprovalRequest, decision: 'approved' | 'denied' | 'deferred') => {
    try {
      const result = await skillApi.decideApproval(request.request_id, decision);
      setTestResult({
        tone: result.decision === 'denied' ? 'error' : 'success',
        title: t('skills.approval_decision_done', { decision: t(`skills.approval_${result.decision}`) }),
        details: [request.capability_name, request.reason],
      });
      await loadApprovals();
      await loadAudit();
    } catch (err) {
      setError(formatSkillError(err, '读取 Skill 安全信息失败，请稍后重试。'));
    }
  };

  const handleOpenUninstall = async (skill: SkillDescriptor) => {
    setUninstallTarget(skill);
    setUninstallPreview(null);
    setModalBusy(true);
    try {
      const preview = await skillApi.uninstallSkill(skill.id, { dryRun: true });
      setUninstallPreview(preview);
    } catch (err) {
      setError(formatSkillError(err, '处理授权请求失败，请稍后重试。'));
    } finally {
      setModalBusy(false);
    }
  };

  const handleConfirmUninstall = async () => {
    if (!uninstallTarget) return;
    setModalBusy(true);
    try {
      const result = await skillApi.uninstallSkill(uninstallTarget.id);
      setTestResult({
        tone: 'success',
        title: t('skills.uninstall_done', { name: uninstallTarget.name }),
        details: [
          result.backup_path ? '已生成本地备份。' : t('skills.path_unavailable'),
          result.removed_path ? '已清理本地安装目录。' : t('skills.path_unavailable'),
        ],
      });
      setUninstallTarget(null);
      setUninstallPreview(null);
      await loadSkills();
      await loadAudit();
    } catch (err) {
      setError(formatSkillError(err, '卸载 Skill 失败，请稍后重试。'));
    } finally {
      setModalBusy(false);
    }
  };

  const handleOpenRollback = (skill: SkillDescriptor) => {
    setRollbackTarget(skill);
    setBackupPathInput('');
  };

  const handleConfirmRollback = async () => {
    if (!rollbackTarget) return;
    setModalBusy(true);
    try {
      const result = await skillApi.rollbackSkill(rollbackTarget.id, backupPathInput);
      setTestResult({
        tone: 'success',
        title: t('skills.rollback_done', { name: rollbackTarget.name }),
        details: [
          result.restored_path ? '已从指定备份恢复。' : t('skills.path_unavailable'),
          result.backup_path ? '已保留回退前备份。' : t('skills.path_unavailable'),
        ],
      });
      setRollbackTarget(null);
      setBackupPathInput('');
      await loadSkills();
      await loadAudit();
    } catch (err) {
      setError(formatSkillError(err, '恢复 Skill 失败，请稍后重试。'));
    } finally {
      setModalBusy(false);
    }
  };

  const handleExport = async (skill: SkillDescriptor) => {
    if (skill.source === 'builtin') return;
    setExportingSkillId(skill.id);
    try {
      const result = await skillApi.exportSkill(skill.id);
      setTestResult({
        tone: result.success ? 'success' : 'error',
        title: result.success
          ? t('skills.export_done', { name: skill.name })
          : t('skills.export_failed', { name: skill.name }),
        details: result.success
          ? [
              result.export_path ? '已导出 Skill 包。' : t('skills.path_unavailable'),
              t('skills.export_boundary'),
            ]
          : sanitizeSkillMessageList(result.errors, t('skills.export_failed', { name: skill.name })),
      });
      await loadAudit();
    } catch (err) {
      setTestResult({
        tone: 'error',
        title: t('skills.export_failed', { name: skill.name }),
        details: err instanceof skillApi.SkillApiError && err.errors.length > 0
          ? sanitizeSkillMessageList(err.errors, t('skills.export_failed', { name: skill.name }))
          : [formatSkillError(err, t('skills.export_failed', { name: skill.name }))],
      });
    } finally {
      setExportingSkillId(null);
    }
  };

  const handleSaveSkillSettings = async (
    skill: SkillDescriptor,
    settings: SkillRuntimeSettings,
  ) => {
    setSavingSkillSettingsId(skill.id);
    try {
      const result = await skillApi.updateSkillRuntimeSettings(skill.id, settings);
      setSkills((current) => current.map((item) => (
        item.id === skill.id
          ? {
              ...item,
              default_parameters: {
                ...item.default_parameters,
                config_values: result.config_values,
                credential_bindings: result.credential_bindings,
              },
            }
          : item
      )));
      setTestResult({
        tone: 'success',
        title: 'Skill 设置已保存',
        details: ['普通配置和凭证引用已写入本地 Skill 元数据。'],
      });
    } catch (err) {
      setTestResult({
        tone: 'error',
        title: 'Skill 设置保存失败',
        details: [formatSkillError(err, 'Skill 设置保存失败')],
      });
    } finally {
      setSavingSkillSettingsId(null);
    }
  };

  const builtinSkills = useMemo(() => skills.filter(s => s.source === 'builtin'), [skills]);
  const userSkills = useMemo(() => skills.filter(s => s.source !== 'builtin'), [skills]);

  return (
    <div className={cn('space-y-6', !embedded && 'py-2')}>
      {/* Tab Navigation */}
      <div className="flex items-center gap-1 p-1 bg-surface-high rounded-xl border border-outline-variant/30 w-fit">
        <TabButton
          active={activeTab === 'skills'}
          onClick={() => setActiveTab('skills')}
          icon={Layers}
          label={t('skills.tab_skills')}
        />
        <TabButton
          active={activeTab === 'approvals'}
          onClick={() => setActiveTab('approvals')}
          icon={ClipboardCheck}
          label={t('skills.tab_approvals')}
        />
        <TabButton
          active={activeTab === 'audit'}
          onClick={() => setActiveTab('audit')}
          icon={History}
          label={t('skills.tab_audit')}
        />
      </div>

      <AnimatePresence mode="wait">
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center justify-between gap-3 text-red-500 text-xs"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} />
              {error}
            </div>
            <button onClick={() => setError(null)} className="p-1 hover:bg-red-500/10 rounded-md">
              <X size={14} />
            </button>
          </motion.div>
        )}

        {testResult && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className={cn(
              'p-4 rounded-xl border font-mono text-[11px] leading-relaxed relative',
              testResult.tone === 'success' ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-600' : 'bg-red-500/5 border-red-500/20 text-red-600'
            )}
          >
            <button
              onClick={() => setTestResult(null)}
              className="absolute top-3 right-3 p-1 hover:bg-foreground/5 rounded-md"
            >
              <X size={14} />
            </button>
            <div className="flex items-center gap-2 mb-2 font-bold text-xs uppercase tracking-wider">
              {testResult.tone === 'success' ? <CheckCircle2 size={14} /> : <Ban size={14} />}
              {testResult.title}
            </div>
            <ul className="space-y-1 opacity-80 list-disc list-inside">
              {testResult.details.map((detail, idx) => (
                <li key={idx}>{detail}</li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {activeTab === 'skills' ? (
          <motion.div
            key="skills-pane"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-8"
          >
            {/* Import Header */}
            <div className="bg-surface-high/50 p-5 rounded-2xl border border-outline-variant/30 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <Plus size={18} />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-foreground">{t('skills.import_title')}</h4>
                  <p className="text-[11px] text-foreground/50">{t('skills.import_zip_desc')}</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold">
                <span className="rounded-full border border-primary/15 bg-primary/5 px-2.5 py-1 text-primary">
                  {t('skills.import_zip_supported')}
                </span>
                <span className="rounded-full border border-amber-500/15 bg-amber-500/5 px-2.5 py-1 text-amber-600">
                  {t('skills.import_runtime_boundary_short')}
                </span>
              </div>

              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Terminal size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground/30" />
                  <input
                    type="text"
                    value={importPath}
                    onChange={e => setImportPath(e.target.value)}
                    placeholder={t('skills.import_placeholder')}
                    className="w-full bg-surface-lowest pl-9 pr-4 py-2.5 rounded-xl border border-outline-variant/50 text-sm focus:outline-none focus:border-primary/40 transition-all placeholder:text-foreground/20"
                  />
                </div>
                <button
                  onClick={handleImport}
                  disabled={importing || !importPath.trim()}
                  className="px-5 py-2.5 bg-primary text-primary-foreground rounded-xl text-sm font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm flex items-center gap-2"
                >
                  {importing ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                  {t('skills.import_btn')}
                </button>
              </div>
            </div>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-12 gap-3 text-foreground/30">
                <Loader2 size={24} className="animate-spin" />
                <span className="text-sm">{t('common.loading')}</span>
              </div>
            ) : (
              <div className="space-y-10">
                <SkillSection
                  title={t('skills.section_user')}
                  skills={userSkills}
                  isBuiltin={false}
                  emptyText={t('skills.empty_user')}
                  onToggle={handleToggle}
                  onTestRun={handleTestRun}
                  onUninstall={handleOpenUninstall}
                  onRollback={handleOpenRollback}
                  onExport={handleExport}
                  onInspectSecurity={handleInspectSecurity}
                  securityAssessments={securityAssessments}
                  securityLoadingId={securityLoadingId}
                  exportingSkillId={exportingSkillId}
                  savingSkillSettingsId={savingSkillSettingsId}
                  onSaveSkillSettings={handleSaveSkillSettings}
                />
                <SkillSection
                  title={t('skills.section_builtin')}
                  skills={builtinSkills}
                  isBuiltin
                  emptyText={t('skills.empty_builtin')}
                  onToggle={handleToggle}
                  onTestRun={handleTestRun}
                  onUninstall={handleOpenUninstall}
                  onRollback={handleOpenRollback}
                  onExport={handleExport}
                  onInspectSecurity={handleInspectSecurity}
                  securityAssessments={securityAssessments}
                  securityLoadingId={securityLoadingId}
                  exportingSkillId={exportingSkillId}
                  savingSkillSettingsId={savingSkillSettingsId}
                  onSaveSkillSettings={handleSaveSkillSettings}
                />
              </div>
            )}
          </motion.div>
        ) : activeTab === 'approvals' ? (
          <ApprovalPane
            approvals={pendingApprovals}
            loading={approvalsLoading}
            onDecision={handleApprovalDecision}
          />
        ) : (
          <motion.div
            key="audit-pane"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            {auditEvents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 gap-4 opacity-30">
                <History size={48} strokeWidth={1} />
                <p className="text-sm">{t('skills.no_audit')}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {auditEvents.map((event, idx) => {
                  const meta = getSkillAuditEventMeta(event.event_type);
                  const expanded = expandedAuditEventId === event.event_id;
                  const details = buildSkillAuditDetails(event);
                  const description = formatSkillAuditDescription(event, meta);
                  const detailPanelId = `skill-audit-detail-${event.event_id}`;
                  return (
                    <motion.div
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: idx * 0.03 }}
                      key={event.event_id}
                      className="p-4 bg-surface-high/40 rounded-xl border border-outline-variant/30 hover:border-outline-variant/60 transition-colors"
                    >
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={detailPanelId}
                        onClick={() => setExpandedAuditEventId(expanded ? null : event.event_id)}
                        className="mb-2 flex w-full items-start justify-between gap-3 rounded-lg text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/35"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className={cn('h-2 w-2 rounded-full', severityColor(event.severity))} />
                            <span className="text-xs font-semibold text-foreground/80">{meta.label}</span>
                            <span className="rounded bg-surface-lowest px-1.5 py-0.5 font-label text-[10px] text-foreground/45">
                              {SKILL_AUDIT_SEVERITY_LABELS[event.severity] ?? event.severity}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] text-foreground/45 leading-relaxed">{meta.hint}</p>
                        </div>
                        <div className="flex flex-shrink-0 items-center gap-2">
                          <span className="text-[10px] text-foreground/30 font-mono whitespace-nowrap">
                            {new Date(event.timestamp).toLocaleString()}
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-md px-2 py-1 font-label text-[10px] text-primary transition-colors">
                            {expanded ? '收起' : '详情'}
                            <ChevronRight
                              size={12}
                              className={cn('transition-transform', expanded && 'rotate-90')}
                            />
                          </span>
                        </div>
                      </button>
                      <p className="text-xs text-foreground/70 leading-relaxed">{description}</p>
                      {(event.capability_id || event.job_id) && (
                        <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-foreground/45">
                          {event.capability_id ? (
                            <span className="rounded bg-surface-lowest px-1.5 py-0.5">
                              已关联 Skill
                            </span>
                          ) : null}
                          {event.job_id ? (
                            <span className="rounded bg-surface-lowest px-1.5 py-0.5">
                              已关联任务
                            </span>
                          ) : null}
                        </div>
                      )}
                      {event.error_message && !expanded && (
                        <div className="mt-2 p-2 bg-red-500/5 rounded border border-red-500/10 text-[10px] text-red-400">
                          {sanitizeSkillUserMessage(event.error_message, '错误详情已隐藏，避免显示内部配置或本地路径。')}
                        </div>
                      )}
                      {expanded && (
                        <div
                          id={detailPanelId}
                          className="mt-3 rounded-lg border border-outline-variant/40 bg-surface-lowest p-3"
                        >
                          <dl className="grid gap-2 md:grid-cols-2">
                            {details.map((item) => (
                              <div key={item.label} className="min-w-0">
                                <dt className="font-label text-[10px] text-foreground/40">{item.label}</dt>
                                <dd className={cn(
                                  'mt-0.5 whitespace-pre-wrap break-words text-[11px] text-foreground/70',
                                  item.mono ? 'font-mono' : 'font-label'
                                )}>
                                  {item.value}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        </div>
                      )}
                    </motion.div>
                  );
                })}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <UninstallSkillModal
        skill={uninstallTarget}
        preview={uninstallPreview}
        busy={modalBusy}
        onCancel={() => {
          if (!modalBusy) {
            setUninstallTarget(null);
            setUninstallPreview(null);
          }
        }}
        onConfirm={handleConfirmUninstall}
      />

      <RollbackSkillModal
        skill={rollbackTarget}
        backupPath={backupPathInput}
        busy={modalBusy}
        onBackupPathChange={setBackupPathInput}
        onCancel={() => {
          if (!modalBusy) {
            setRollbackTarget(null);
            setBackupPathInput('');
          }
        }}
        onConfirm={handleConfirmRollback}
      />
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all',
        active ? 'bg-surface-lowest text-primary shadow-sm' : 'text-foreground/40 hover:text-foreground/70'
      )}
    >
      <Icon size={14} />
      {label}
    </button>
  );
}

// --- Sub-components ---

function SkillSection({
  title,
  skills,
  isBuiltin,
  emptyText,
  onToggle,
  onTestRun,
  onUninstall,
  onRollback,
  onExport,
  onInspectSecurity,
  securityAssessments,
  securityLoadingId,
  exportingSkillId,
  savingSkillSettingsId,
  onSaveSkillSettings,
}: {
  title: string;
  skills: SkillDescriptor[];
  isBuiltin: boolean;
  emptyText: string;
  onToggle: (skill: SkillDescriptor) => void;
  onTestRun: (skillId: string) => void;
  onUninstall: (skill: SkillDescriptor) => void;
  onRollback: (skill: SkillDescriptor) => void;
  onExport: (skill: SkillDescriptor) => void;
  onInspectSecurity: (skill: SkillDescriptor) => void;
  onSaveSkillSettings: (skill: SkillDescriptor, settings: SkillRuntimeSettings) => void;
  securityAssessments: Record<string, SkillSecurityAssessment>;
  securityLoadingId: string | null;
  exportingSkillId: string | null;
  savingSkillSettingsId: string | null;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 px-1">
        <h3 className="text-sm font-bold text-foreground/80 uppercase tracking-wider">{title}</h3>
        <div className="h-px flex-1 bg-outline-variant/30" />
        <span className="text-[10px] font-mono text-foreground/30">{skills.length}</span>
      </div>

      {skills.length === 0 ? (
        <div className="py-10 text-center border-2 border-dashed border-outline-variant/30 rounded-2xl text-foreground/20 text-xs italic">
          {emptyText}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3">
          <AnimatePresence>
            {skills.map((skill, idx) => (
              <motion.div
                key={skill.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05 }}
              >
                <SkillCard
                  skill={skill}
                  isBuiltin={isBuiltin}
                  onToggle={onToggle}
                  onTestRun={onTestRun}
                  onUninstall={onUninstall}
                  onRollback={onRollback}
                  onExport={onExport}
                  onInspectSecurity={onInspectSecurity}
                  securityAssessment={securityAssessments[skill.id]}
                  securityLoading={securityLoadingId === skill.id}
                  exportBusy={exportingSkillId === skill.id}
                  settingsSaving={savingSkillSettingsId === skill.id}
                  onSaveSkillSettings={onSaveSkillSettings}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

function SkillCard({
  skill,
  isBuiltin,
  onToggle,
  onTestRun,
  onUninstall,
  onRollback,
  onExport,
  onInspectSecurity,
  onSaveSkillSettings,
  securityAssessment,
  securityLoading,
  exportBusy,
  settingsSaving,
}: {
  skill: SkillDescriptor;
  isBuiltin: boolean;
  onToggle: (skill: SkillDescriptor) => void;
  onTestRun: (skillId: string) => void;
  onUninstall: (skill: SkillDescriptor) => void;
  onRollback: (skill: SkillDescriptor) => void;
  onExport: (skill: SkillDescriptor) => void;
  onInspectSecurity: (skill: SkillDescriptor) => void;
  onSaveSkillSettings: (skill: SkillDescriptor, settings: SkillRuntimeSettings) => void;
  securityAssessment?: SkillSecurityAssessment;
  securityLoading: boolean;
  exportBusy: boolean;
  settingsSaving: boolean;
}) {
  const { t } = useI18n();
  const isEnabled = !skill.disabled_reason;
  const hasScripts = skill.script_policy?.has_scripts;
  const permissions = skill.default_parameters.permissions;
  const permissionMap = isPermissionMap(permissions) ? permissions : {};
  const highRiskPermissions = HIGH_RISK_PERMISSIONS.filter(permission => permissionMap[permission]);
  const highRisk = highRiskPermissions.length > 0;
  const highRiskPermissionLabel = formatSkillSecurityList(highRiskPermissions, '', 'operation');
  const configFields = readSkillConfigFields(skill);
  const requiredCredentials = readSkillRequiredCredentials(skill);
  const runtimeSettings = readSkillRuntimeSettings(skill);

  return (
    <div
      className={cn(
        'group relative p-5 rounded-2xl border transition-all duration-300',
        isEnabled
          ? 'bg-surface-low border-outline-variant/50 hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5'
          : 'bg-surface-high/30 border-red-500/10 grayscale-[0.5] opacity-60'
      )}
    >
      <div className="flex gap-4">
        {/* Icon / Status */}
        <div className={cn(
          'w-10 h-10 rounded-xl flex items-center justify-center shrink-0 transition-colors',
          isEnabled ? 'bg-primary/5 text-primary group-hover:bg-primary group-hover:text-white' : 'bg-foreground/5 text-foreground/30'
        )}>
          {skill.kind === 'prompt-only' ? <Database size={20} /> :
           skill.kind === 'workflow' ? <Layers size={20} /> :
           <Terminal size={20} />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4 mb-1">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-bold text-foreground truncate max-w-[200px]">{skill.name}</h4>
              <div className={cn('px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider', sourceClass(skill.source))}>
                {t(`skills.source_${skill.source}`)}
              </div>
              <div className="px-1.5 py-0.5 rounded bg-surface-highest text-foreground/40 text-[9px] font-mono">
                v{skill.version}
              </div>
              {skill.trust_level === 'untrusted' && (
                <div className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-500 text-[9px] font-bold flex items-center gap-1">
                  <Shield size={10} />
                  {t('skills.trust_untrusted')}
                </div>
              )}
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => onTestRun(skill.id)}
                className="p-1.5 text-foreground/40 hover:text-primary hover:bg-primary/10 rounded-lg transition-all"
                title={t('skills.test_run')}
              >
                <Play size={16} />
              </button>
              <button
                onClick={() => onInspectSecurity(skill)}
                className={cn(
                  'p-1.5 rounded-lg transition-all',
                  securityAssessment ? 'text-primary bg-primary/10' : 'text-foreground/40 hover:text-primary hover:bg-primary/10'
                )}
                title={t('skills.security_view_for', { name: skill.name })}
                aria-label={t('skills.security_view_for', { name: skill.name })}
              >
                {securityLoading ? <Loader2 size={16} className="animate-spin" /> : <Eye size={16} />}
              </button>
              {!isBuiltin && (
                <>
                  <button
                    onClick={() => onRollback(skill)}
                    className="p-1.5 text-foreground/40 hover:text-amber-500 hover:bg-amber-500/10 rounded-lg transition-all"
                    title={t('skills.rollback')}
                  >
                    <RotateCcw size={16} />
                  </button>
                  <button
                    onClick={() => onExport(skill)}
                    disabled={exportBusy}
                    className="p-1.5 text-foreground/40 hover:text-primary hover:bg-primary/10 rounded-lg transition-all disabled:cursor-wait disabled:opacity-50"
                    title={t('skills.export')}
                    aria-label={t('skills.export_for', { name: skill.name })}
                  >
                    {exportBusy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                  </button>
                  <button
                    onClick={() => onToggle(skill)}
                    className={cn(
                      'p-1.5 rounded-lg transition-all',
                      isEnabled ? 'text-red-400 hover:text-red-500 hover:bg-red-500/10' : 'text-emerald-400 hover:text-emerald-500 hover:bg-emerald-500/10'
                    )}
                    title={isEnabled ? t('skills.disable') : t('skills.enable')}
                  >
                    {isEnabled ? <Ban size={16} /> : <CheckCircle2 size={16} />}
                  </button>
                  <button
                    onClick={() => onUninstall(skill)}
                    className="p-1.5 text-foreground/40 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all"
                    title={t('skills.uninstall')}
                  >
                    <Trash2 size={16} />
                  </button>
                </>
              )}
            </div>
          </div>

          <p className="text-xs text-foreground/50 leading-relaxed line-clamp-2 mb-3">
            {skill.description}
          </p>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {/* Badges for technical metadata */}
            <div className="flex items-center gap-3 text-[10px] text-foreground/30 font-medium">
              <div className="flex items-center gap-1">
                <Cpu size={12} className="opacity-50" />
                {skill.kind}
              </div>
              <div className="flex items-center gap-1">
                <ExternalLink size={12} className="opacity-50" />
                {skill.entry_mode}
              </div>
            </div>

            {/* Risk Indicators */}
            {(hasScripts || highRisk) && (
              <div className="flex items-center gap-2">
                {hasScripts && (
                  <div className="flex items-center gap-1 text-[10px] text-amber-500 font-bold bg-amber-500/5 px-2 py-0.5 rounded-full border border-amber-500/10">
                    <Lock size={10} />
                    {t('skills.scripts_blocked')}
                  </div>
                )}
                {highRisk && (
                  <div className="flex items-center gap-1 text-[10px] text-red-500 font-bold bg-red-500/5 px-2 py-0.5 rounded-full border border-red-500/10">
                    <Shield size={10} />
                    {t('skills.high_risk', { permissions: highRiskPermissionLabel })}
                  </div>
                )}
              </div>
            )}
          </div>

          {securityAssessment && (
            <SecurityAssessmentPanel assessment={securityAssessment} />
          )}
          {!isBuiltin && (configFields.length > 0 || requiredCredentials.length > 0) && (
            <SkillRuntimeSettingsPanel
              skill={skill}
              configFields={configFields}
              requiredCredentials={requiredCredentials}
              initialSettings={runtimeSettings}
              saving={settingsSaving}
              onSave={(settings) => onSaveSkillSettings(skill, settings)}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function SecurityAssessmentPanel({ assessment }: { assessment: SkillSecurityAssessment }) {
  const { t } = useI18n();
  const deniedOperations = formatSkillSecurityList(
    assessment.denied_operations,
    t('skills.security_none'),
    'operation',
  );
  const requiredControls = formatSkillSecurityList(
    assessment.required_sandbox_controls,
    t('skills.security_none'),
    'sandbox',
  );
  const blockReason = formatSkillSecurityReason(
    assessment.block_reason,
    '拦截详情已隐藏，避免显示内部策略字段。',
  );
  const approvalReason = formatSkillSecurityReason(
    assessment.approval_reason,
    '审批详情已隐藏，避免显示内部策略字段。',
  );

  return (
    <div className="mt-4 rounded-xl border border-outline-variant/40 bg-surface-high/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-foreground/55">
          <Shield size={13} />
          {t('skills.security_panel_title')}
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold', riskClass(assessment.risk_level))}>
          {t('skills.security_risk', { risk: formatSkillRiskLevel(assessment.risk_level) })}
        </span>
      </div>
      <div className="grid gap-2 text-[11px] leading-relaxed md:grid-cols-2">
        <SecurityField label={t('skills.security_runtime_gate')} value={formatSkillRuntimeGate(assessment.runtime_gate)} />
        <SecurityField
          label={t('skills.security_runtime_executable')}
          value={assessment.runtime_executable ? t('skills.security_yes') : t('skills.security_no')}
        />
        <SecurityField
          label={t('skills.security_enable_approval')}
          value={assessment.enable_requires_approval ? t('skills.security_yes') : t('skills.security_no')}
        />
        <SecurityField label={t('skills.security_denied_operations')} value={deniedOperations} />
        <SecurityField label={t('skills.security_sandbox_controls')} value={requiredControls} wide />
        {blockReason && (
          <SecurityField label={t('skills.security_block_reason')} value={blockReason} wide />
        )}
        {approvalReason && (
          <SecurityField label={t('skills.security_approval_reason')} value={approvalReason} wide />
        )}
      </div>
    </div>
  );
}

function SecurityField({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('rounded-lg border border-outline-variant/30 bg-surface-lowest/40 p-2', wide && 'md:col-span-2')}>
      <div className="mb-1 text-[9px] font-bold uppercase tracking-wider text-foreground/35">{label}</div>
      <div className="break-words font-label text-[10px] text-foreground/65">{value}</div>
    </div>
  );
}

function SkillRuntimeSettingsPanel({
  skill,
  configFields,
  requiredCredentials,
  initialSettings,
  saving,
  onSave,
}: {
  skill: SkillDescriptor;
  configFields: SkillConfigField[];
  requiredCredentials: SkillRequiredCredential[];
  initialSettings: SkillRuntimeSettings;
  saving: boolean;
  onSave: (settings: SkillRuntimeSettings) => void;
}) {
  const [configValues, setConfigValues] = useState<Record<string, string>>(() => ({
    ...Object.fromEntries(configFields.map((field) => [field.env, field.default ?? ''])),
    ...initialSettings.config_values,
  }));
  const [credentialBindings, setCredentialBindings] = useState<Record<string, string>>(
    () => ({ ...initialSettings.credential_bindings }),
  );
  const configSignature = JSON.stringify(initialSettings.config_values);
  const credentialSignature = JSON.stringify(initialSettings.credential_bindings);

  useEffect(() => {
    setConfigValues({
      ...Object.fromEntries(configFields.map((field) => [field.env, field.default ?? ''])),
      ...initialSettings.config_values,
    });
    setCredentialBindings({ ...initialSettings.credential_bindings });
  }, [skill.id, configSignature, credentialSignature]);

  const missingRequiredConfig = configFields.some(
    (field) => field.required && !configValues[field.env]?.trim(),
  );
  const missingRequiredCredential = requiredCredentials.some(
    (item) => item.required && !credentialBindings[item.env]?.trim(),
  );
  const canSave = !missingRequiredConfig && !missingRequiredCredential && !saving;

  return (
    <div className="mt-4 rounded-xl border border-outline-variant/40 bg-surface-high/40 p-3">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-foreground/55">
            <Database size={13} />
            Skill 设置
          </div>
          <p className="mt-1 text-[10px] leading-relaxed text-foreground/45">
            按 Skill 声明自动生成。普通配置可选预设也可手动填写，敏感信息只绑定已保存凭证。
          </p>
        </div>
        <button
          type="button"
          disabled={!canSave}
          onClick={() => onSave({
            config_values: configValues,
            credential_bindings: credentialBindings,
          })}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary/10 px-3 py-1.5 text-[11px] font-semibold text-primary hover:bg-primary/15 disabled:opacity-50"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
          保存
        </button>
      </div>

      {configFields.length > 0 && (
        <div className="space-y-3">
          {configFields.map((field, index) => (
            <SkillConfigFieldControl
              key={field.id}
              field={field}
              index={index}
              value={configValues[field.env] ?? ''}
              onChange={(value) => setConfigValues((current) => ({
                ...current,
                [field.env]: value,
              }))}
            />
          ))}
        </div>
      )}

      {requiredCredentials.length > 0 && (
        <div className="mt-4 space-y-4">
          {requiredCredentials.map((requirement) => (
            <CredentialPicker
              key={requirement.id}
              requirement={requirement}
              value={credentialBindings[requirement.env] ?? null}
              onChange={(id) => setCredentialBindings((current) => ({
                ...current,
                [requirement.env]: id ?? '',
              }))}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SkillConfigFieldControl({
  field,
  index,
  value,
  onChange,
}: {
  field: SkillConfigField;
  index: number;
  value: string;
  onChange: (value: string) => void;
}) {
  const label = formatDynamicConfigFieldLabel(field.label, index);
  const description = formatDynamicDescription(field.description);
  const manualHint = getDynamicConfigManualEntryHint(field);
  return (
    <label className="block space-y-1">
      <span className="text-[11px] font-medium text-foreground/70">
        {label}
        {field.required && <span className="ml-0.5 text-red-500" aria-label="必填">*</span>}
      </span>
      {description && (
        <span className="block text-[10px] leading-relaxed text-foreground/45">
          {description}
        </span>
      )}
      {field.type === 'select' && field.options && field.options.length > 0 && (
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-lg border border-outline-variant bg-surface-lowest px-2 py-1.5 text-xs text-foreground"
        >
          <option value="">手动填写 / 不使用预设</option>
          {field.options.map((option, optionIndex) => (
            <option key={option.value} value={option.value}>
              {formatDynamicOptionLabel(option.label, optionIndex)}
            </option>
          ))}
        </select>
      )}
      {field.type === 'boolean' ? (
        <button
          type="button"
          role="switch"
          aria-checked={value === 'true'}
          onClick={() => onChange(value === 'true' ? 'false' : 'true')}
          className={cn(
            'inline-flex w-full items-center justify-between rounded-lg border px-3 py-2 text-xs transition-colors',
            value === 'true'
              ? 'border-primary/40 bg-primary/10 text-primary'
              : 'border-outline-variant bg-surface-lowest text-foreground/60',
          )}
        >
          <span>{value === 'true' ? '已开启' : '已关闭'}</span>
          <span className="text-[10px] text-foreground/45">点击切换</span>
        </button>
      ) : (
        <input
          type={field.type === 'number' ? 'number' : 'text'}
          value={value}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? undefined}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.type === 'select' ? '手动填写自定义取值' : manualHint}
          className="w-full rounded-lg border border-outline-variant bg-surface-lowest px-2 py-1.5 text-xs text-foreground"
        />
      )}
      {field.type !== 'boolean' && (
        <span className="block text-[10px] leading-relaxed text-foreground/40">
          {manualHint}
        </span>
      )}
    </label>
  );
}

function riskClass(riskLevel: string): string {
  switch (riskLevel) {
    case 'critical':
      return 'bg-red-500/10 text-red-600 border border-red-500/15';
    case 'high':
      return 'bg-amber-500/10 text-amber-700 border border-amber-500/15';
    case 'medium':
      return 'bg-blue-500/10 text-blue-600 border border-blue-500/15';
    default:
      return 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/15';
  }
}

function ApprovalPane({
  approvals,
  loading,
  onDecision,
}: {
  approvals: SkillApprovalRequest[];
  loading: boolean;
  onDecision: (request: SkillApprovalRequest, decision: 'approved' | 'denied' | 'deferred') => void;
}) {
  const { t } = useI18n();

  return (
    <motion.div
      key="approvals-pane"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="space-y-3"
    >
      {loading ? (
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-foreground/30">
          <Loader2 size={24} className="animate-spin" />
          <span className="text-sm">{t('skills.approvals_loading')}</span>
        </div>
      ) : approvals.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4 opacity-30 border-2 border-dashed border-outline-variant/30 rounded-2xl">
          <ClipboardCheck size={48} strokeWidth={1} />
          <p className="text-sm">{t('skills.approvals_empty')}</p>
        </div>
      ) : (
        approvals.map(request => {
          const capabilityName = sanitizeSkillUserMessage(request.capability_name, '受保护能力');
          const reason = formatSkillSecurityReason(
            request.reason,
            '此操作需要授权后才会继续。',
          ) ?? '此操作需要授权后才会继续。';
          return (
          <div
            key={request.request_id}
            className="p-4 bg-surface-high/40 rounded-xl border border-outline-variant/30 space-y-3"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-600 flex items-center justify-center">
                    <Shield size={16} />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-foreground">{capabilityName}</h4>
                    <p className="text-[10px] text-foreground/45">需要授权后才会执行</p>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1 text-[10px] text-foreground/35 font-mono">
                <Clock3 size={12} />
                {new Date(request.timestamp).toLocaleString()}
              </div>
            </div>
            <p className="text-xs text-foreground/60 leading-relaxed">{reason}</p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => onDecision(request, 'deferred')}
                className="px-3 py-1.5 rounded-lg border border-outline-variant text-[11px] text-foreground/60 hover:text-foreground hover:bg-surface-lowest"
              >
                {t('skills.approval_deferred')}
              </button>
              <button
                type="button"
                onClick={() => onDecision(request, 'denied')}
                className="px-3 py-1.5 rounded-lg bg-red-500/10 text-red-500 text-[11px] font-semibold hover:bg-red-500/15"
              >
                {t('skills.approval_denied')}
              </button>
              <button
                type="button"
                onClick={() => onDecision(request, 'approved')}
                className="px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-600 text-[11px] font-semibold hover:bg-emerald-500/15"
              >
                {t('skills.approval_approved')}
              </button>
            </div>
          </div>
          );
        })
      )}
    </motion.div>
  );
}

function UninstallSkillModal({
  skill,
  preview,
  busy,
  onCancel,
  onConfirm,
}: {
  skill: SkillDescriptor | null;
  preview: SkillUninstallResult | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <Modal
      open={skill !== null}
      onClose={onCancel}
      showCloseButton={false}
      closeOnBackdrop={false}
      role="alertdialog"
      labelledBy="skill-uninstall-title"
      describedBy="skill-uninstall-desc"
      initialFocusRef={cancelRef}
      size="lg"
    >
      <ModalHeader className="space-y-2">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-red-500/10 text-red-500 flex items-center justify-center">
            <Trash2 size={18} />
          </div>
          <div>
            <h3 id="skill-uninstall-title" className="text-base font-bold text-foreground">
              {t('skills.uninstall_confirm_title')}
            </h3>
            <p id="skill-uninstall-desc" className="text-xs text-foreground/55 leading-relaxed">
              {skill ? t('skills.uninstall_confirm_desc', { name: skill.name }) : ''}
            </p>
          </div>
        </div>
      </ModalHeader>
      <ModalBody className="space-y-3">
        <div className="rounded-xl border border-red-500/15 bg-red-500/5 p-3 text-xs text-red-600 leading-relaxed">
          {t('skills.uninstall_warning')}
        </div>
        <PathPreview label={t('skills.backup_path_label')} value={preview?.backup_path ?? null} loading={busy && !preview} />
        <PathPreview label={t('skills.removed_path_label')} value={preview?.removed_path ?? null} loading={busy && !preview} />
      </ModalBody>
      <ModalFooter>
        <button
          ref={cancelRef}
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="px-4 py-2 rounded-lg border border-outline-variant text-xs font-semibold text-foreground/65 hover:text-foreground hover:bg-surface-high disabled:opacity-50"
        >
          {t('common.cancel')}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy || !preview}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700 disabled:opacity-50"
        >
          {busy && <Loader2 size={14} className="animate-spin" />}
          {t('skills.uninstall_confirm')}
        </button>
      </ModalFooter>
    </Modal>
  );
}

function RollbackSkillModal({
  skill,
  backupPath,
  busy,
  onBackupPathChange,
  onCancel,
  onConfirm,
}: {
  skill: SkillDescriptor | null;
  backupPath: string;
  busy: boolean;
  onBackupPathChange: (value: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <Modal
      open={skill !== null}
      onClose={onCancel}
      showCloseButton={false}
      closeOnBackdrop={false}
      role="dialog"
      labelledBy="skill-rollback-title"
      describedBy="skill-rollback-desc"
      initialFocusRef={cancelRef}
      size="lg"
    >
      <ModalHeader className="space-y-2">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-500/10 text-amber-600 flex items-center justify-center">
            <RotateCcw size={18} />
          </div>
          <div>
            <h3 id="skill-rollback-title" className="text-base font-bold text-foreground">
              {t('skills.rollback_title')}
            </h3>
            <p id="skill-rollback-desc" className="text-xs text-foreground/55 leading-relaxed">
              {skill ? t('skills.rollback_desc', { name: skill.name }) : ''}
            </p>
          </div>
        </div>
      </ModalHeader>
      <ModalBody className="space-y-4">
        <label className="block space-y-2">
          <span className="text-xs font-semibold text-foreground/65">{t('skills.rollback_backup_path')}</span>
          <input
            type="text"
            value={backupPath}
            onChange={event => onBackupPathChange(event.target.value)}
            placeholder={t('skills.rollback_latest_placeholder')}
            className="w-full bg-surface-lowest px-3 py-2.5 rounded-xl border border-outline-variant/50 text-xs focus:outline-none focus:border-primary/40 transition-all placeholder:text-foreground/25"
          />
        </label>
        <div className="rounded-xl border border-amber-500/15 bg-amber-500/5 p-3 text-xs text-amber-700 leading-relaxed">
          {t('skills.rollback_hint')}
        </div>
      </ModalBody>
      <ModalFooter>
        <button
          ref={cancelRef}
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="px-4 py-2 rounded-lg border border-outline-variant text-xs font-semibold text-foreground/65 hover:text-foreground hover:bg-surface-high disabled:opacity-50"
        >
          {t('common.cancel')}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600 text-white text-xs font-bold hover:bg-amber-700 disabled:opacity-50"
        >
          {busy && <Loader2 size={14} className="animate-spin" />}
          {t('skills.rollback_confirm')}
        </button>
      </ModalFooter>
    </Modal>
  );
}

function PathPreview({ label, value, loading }: { label: string; value: string | null; loading: boolean }) {
  const { t } = useI18n();
  const displayValue = value ? '已准备本地路径。' : t('skills.path_unavailable');

  return (
    <div className="rounded-xl border border-outline-variant/40 bg-surface-high/30 p-3">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-foreground/40">{label}</div>
      <div className="font-label text-[11px] text-foreground/65">
        {loading ? t('common.loading') : displayValue}
      </div>
    </div>
  );
}

function sourceClass(source: string): string {
  switch (source) {
    case 'builtin': return 'bg-emerald-500/10 text-emerald-500';
    case 'imported': return 'bg-primary/10 text-primary';
    case 'experimental': return 'bg-amber-500/10 text-amber-500';
    default: return 'bg-foreground/5 text-foreground/40';
  }
}

function severityColor(severity: string): string {
  switch (severity) {
    case 'error':
    case 'critical': return 'bg-red-500';
    case 'warning': return 'bg-amber-500';
    default: return 'bg-primary';
  }
}

function isPermissionMap(value: unknown): value is Partial<Record<PermissionKey, boolean>> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }
  return Object.values(value as Record<string, unknown>).every(item => typeof item === 'boolean');
}

export default SkillManager;
