/**
 * SkillManager component (TASK-189).
 *
 * Displays builtin vs user skills in separate sections,
 * with import, enable/disable, test-run, and audit capabilities.
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Layers, Shield, Play, Ban, CheckCircle2, AlertTriangle,
  History, Download, Plus, Info, ChevronRight, X, Loader2,
  Lock, Terminal, Cpu, Database, Eye, ExternalLink,
  Trash2, RotateCcw, ClipboardCheck, Clock3, type LucideIcon,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';
import { Modal, ModalBody, ModalFooter, ModalHeader } from '@/components/ui/Modal';
import type {
  PermissionKey,
  SkillDescriptor,
  SkillAuditEvent,
  SkillApprovalRequest,
  SkillSecurityAssessment,
  SkillUninstallResult,
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

const readStringField = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }

  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
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
          details: error.errors.length > 0 ? error.errors : [error.message],
        };
      default:
        return {
          tone: 'error',
          title: t('skills.import_failed_title'),
          details: error.errors.length > 0 ? error.errors : [error.message],
        };
    }
  }

  return {
    tone: 'error',
    title: t('skills.import_failed_title'),
    details: [error instanceof Error ? error.message : String(error)],
  };
};

const buildSkillTestDetails = (result: SkillTestRunResult, t: Translate): string[] => {
  const details: string[] = [
    t('skills.test_duration', { ms: result.execution_time_ms }),
  ];
  const outputText = result.output_text.trim();
  const executionMode = readStringField(result.structured_output.execution_mode);

  if (outputText.length > 0) {
    details.unshift(t('skills.test_output', { output: truncateText(outputText, 240) }));
  }

  if (executionMode) {
    details.push(t('skills.test_execution_mode', { mode: executionMode }));
  }

  if (result.evidence_refs.length > 0) {
    details.push(t('skills.test_evidence_count', { count: result.evidence_refs.length }));
  }

  if (result.warnings.length > 0) {
    details.push(t('skills.test_warnings', { count: result.warnings.length }));
  }

  if (result.audit_id) {
    details.push(t('skills.test_audit_id', { auditId: result.audit_id }));
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

  const loadSkills = useCallback(async () => {
    try {
      setLoading(true);
      const data = await skillApi.listSkills();
      setSkills(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
      setError(err instanceof Error ? err.message : String(err));
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
          details: [err.message],
        });
        setActiveTab('approvals');
        await loadApprovals();
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
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
        details: [err instanceof Error ? err.message : String(err)],
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
      setError(err instanceof Error ? err.message : String(err));
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
      setError(err instanceof Error ? err.message : String(err));
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
      setError(err instanceof Error ? err.message : String(err));
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
          t('skills.backup_path', { path: result.backup_path ?? t('skills.path_unavailable') }),
          t('skills.removed_path', { path: result.removed_path ?? t('skills.path_unavailable') }),
        ],
      });
      setUninstallTarget(null);
      setUninstallPreview(null);
      await loadSkills();
      await loadAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
          t('skills.restored_path', { path: result.restored_path }),
          t('skills.backup_path', { path: result.backup_path }),
        ],
      });
      setRollbackTarget(null);
      setBackupPathInput('');
      await loadSkills();
      await loadAudit();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setModalBusy(false);
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
                  onInspectSecurity={handleInspectSecurity}
                  securityAssessments={securityAssessments}
                  securityLoadingId={securityLoadingId}
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
                  onInspectSecurity={handleInspectSecurity}
                  securityAssessments={securityAssessments}
                  securityLoadingId={securityLoadingId}
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
                {auditEvents.map((event, idx) => (
                  <motion.div
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.03 }}
                    key={event.event_id}
                    className="p-4 bg-surface-high/40 rounded-xl border border-outline-variant/30 hover:border-outline-variant/60 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className={cn('w-2 h-2 rounded-full', severityColor(event.severity))} />
                        <span className="text-[11px] font-bold uppercase tracking-widest text-foreground/70">
                          {event.event_type}
                        </span>
                      </div>
                      <span className="text-[10px] text-foreground/30 font-mono">
                        {new Date(event.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <p className="text-xs text-foreground/70 leading-relaxed">{event.description}</p>
                    {event.error_message && (
                      <div className="mt-2 p-2 bg-red-500/5 rounded border border-red-500/10 text-[10px] text-red-400 font-mono">
                        {event.error_message}
                      </div>
                    )}
                  </motion.div>
                ))}
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
  onInspectSecurity,
  securityAssessments,
  securityLoadingId,
}: {
  title: string;
  skills: SkillDescriptor[];
  isBuiltin: boolean;
  emptyText: string;
  onToggle: (skill: SkillDescriptor) => void;
  onTestRun: (skillId: string) => void;
  onUninstall: (skill: SkillDescriptor) => void;
  onRollback: (skill: SkillDescriptor) => void;
  onInspectSecurity: (skill: SkillDescriptor) => void;
  securityAssessments: Record<string, SkillSecurityAssessment>;
  securityLoadingId: string | null;
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
                  onInspectSecurity={onInspectSecurity}
                  securityAssessment={securityAssessments[skill.id]}
                  securityLoading={securityLoadingId === skill.id}
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
  onInspectSecurity,
  securityAssessment,
  securityLoading,
}: {
  skill: SkillDescriptor;
  isBuiltin: boolean;
  onToggle: (skill: SkillDescriptor) => void;
  onTestRun: (skillId: string) => void;
  onUninstall: (skill: SkillDescriptor) => void;
  onRollback: (skill: SkillDescriptor) => void;
  onInspectSecurity: (skill: SkillDescriptor) => void;
  securityAssessment?: SkillSecurityAssessment;
  securityLoading: boolean;
}) {
  const { t } = useI18n();
  const isEnabled = !skill.disabled_reason;
  const hasScripts = skill.script_policy?.has_scripts;
  const permissions = skill.default_parameters.permissions;
  const permissionMap = isPermissionMap(permissions) ? permissions : {};
  const highRiskPermissions = HIGH_RISK_PERMISSIONS.filter(permission => permissionMap[permission]);
  const highRisk = highRiskPermissions.length > 0;

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
                    {t('skills.high_risk', { permissions: highRiskPermissions.join(', ') })}
                  </div>
                )}
              </div>
            )}
          </div>

          {securityAssessment && (
            <SecurityAssessmentPanel assessment={securityAssessment} />
          )}
        </div>
      </div>
    </div>
  );
}

function SecurityAssessmentPanel({ assessment }: { assessment: SkillSecurityAssessment }) {
  const { t } = useI18n();
  const deniedOperations = assessment.denied_operations.length > 0
    ? assessment.denied_operations.join(', ')
    : t('skills.security_none');
  const requiredControls = assessment.required_sandbox_controls.length > 0
    ? assessment.required_sandbox_controls.join(', ')
    : t('skills.security_none');

  return (
    <div className="mt-4 rounded-xl border border-outline-variant/40 bg-surface-high/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-foreground/55">
          <Shield size={13} />
          {t('skills.security_panel_title')}
        </div>
        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold', riskClass(assessment.risk_level))}>
          {t('skills.security_risk', { risk: assessment.risk_level })}
        </span>
      </div>
      <div className="grid gap-2 text-[11px] leading-relaxed md:grid-cols-2">
        <SecurityField label={t('skills.security_runtime_gate')} value={assessment.runtime_gate} />
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
        {assessment.block_reason && (
          <SecurityField label={t('skills.security_block_reason')} value={assessment.block_reason} wide />
        )}
        {assessment.approval_reason && (
          <SecurityField label={t('skills.security_approval_reason')} value={assessment.approval_reason} wide />
        )}
      </div>
    </div>
  );
}

function SecurityField({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn('rounded-lg border border-outline-variant/30 bg-surface-lowest/40 p-2', wide && 'md:col-span-2')}>
      <div className="mb-1 text-[9px] font-bold uppercase tracking-wider text-foreground/35">{label}</div>
      <div className="break-words font-mono text-[10px] text-foreground/65">{value}</div>
    </div>
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
        approvals.map(request => (
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
                    <h4 className="text-sm font-bold text-foreground">{request.capability_name}</h4>
                    <p className="text-[10px] font-mono text-foreground/35">{request.capability_id}</p>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1 text-[10px] text-foreground/35 font-mono">
                <Clock3 size={12} />
                {new Date(request.timestamp).toLocaleString()}
              </div>
            </div>
            <p className="text-xs text-foreground/60 leading-relaxed">{request.reason}</p>
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
        ))
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

  return (
    <div className="rounded-xl border border-outline-variant/40 bg-surface-high/30 p-3">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-foreground/40">{label}</div>
      <div className="font-mono text-[11px] text-foreground/65 break-all">
        {loading ? t('common.loading') : value ?? t('skills.path_unavailable')}
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
