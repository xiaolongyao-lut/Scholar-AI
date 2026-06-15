import { useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getApiBaseUrl } from '@/services/apiBaseUrl';
import axios from 'axios';

interface LinterIssue {
  field: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  current: string | null;
  suggested: string | null;
}

interface LinterResult {
  material_id: string;
  title: string;
  issues: LinterIssue[];
  has_errors: boolean;
  has_warnings: boolean;
}

interface ApplyFixesResponse {
  status: 'applied';
  material_id: string;
  fixed_fields: string[];
  result: LinterResult;
}

interface MetadataLinterPanelProps {
  projectId: string;
  onComplete?: () => void;
}

const CASE_STYLES = ['title', 'sentence', 'original'] as const;
type CaseStyle = (typeof CASE_STYLES)[number];

const SEVERITY_CONFIG = {
  error: {
    icon: AlertTriangle,
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-500/10',
    borderColor: 'border-red-300 dark:border-red-700',
  },
  warning: {
    icon: AlertTriangle,
    color: 'text-amber-600 dark:text-amber-400',
    bgColor: 'bg-amber-50 dark:bg-amber-500/10',
    borderColor: 'border-amber-300 dark:border-amber-700',
  },
  info: {
    icon: Info,
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-500/10',
    borderColor: 'border-blue-300 dark:border-blue-700',
  },
};

function isCaseStyle(value: string): value is CaseStyle {
  return CASE_STYLES.some((style) => style === value);
}

function getIssueBaseField(field: string): string {
  return field.replace(/\[.*\]/, '');
}

function getFixableFields(result: LinterResult): string[] {
  return Array.from(
    new Set(
      result.issues
        .filter((issue) => issue.suggested !== null)
        .map((issue) => getIssueBaseField(issue.field)),
    ),
  );
}

function getResultSeverity(result: LinterResult): LinterIssue['severity'] {
  if (result.has_errors) return 'error';
  if (result.has_warnings) return 'warning';
  return 'info';
}

export function MetadataLinterPanel({ projectId, onComplete }: MetadataLinterPanelProps) {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<LinterResult[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [expandedMaterial, setExpandedMaterial] = useState<string | null>(null);
  const [caseStyle, setCaseStyle] = useState<CaseStyle>('title');
  const [applyingFixes, setApplyingFixes] = useState<Set<string>>(new Set());
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleRunLinter = async () => {
    setRunning(true);
    setResults([]);
    setErrorMessage(null);
    setSuccessMessage(null);
    setExpanded(false);

    try {
      const baseUrl = getApiBaseUrl();

      // 调用异步端点创建后台任务
      console.log('[Linter] 创建后台任务...');
      const { data: taskData } = await axios.post(`${baseUrl}/api/linter/lint/batch/async`, {
        project_id: projectId,
        preferred_case: caseStyle,
      }, { timeout: 5000 });

      const taskId = taskData.task_id;
      console.log('[Linter] 任务已创建:', taskId);

      // 显示提示消息
      setSuccessMessage('检查任务已在后台启动，请到"任务中心"查看进度');

      // 可选：自动跳转到任务中心
      // window.location.href = `/jobs?highlight=${taskId}`;

    } catch (err) {
      console.error('Linter 启动失败:', err);
      setErrorMessage('启动 Linter 失败，请稍后重试。');
    } finally {
      setRunning(false);
    }
  };

  const handleApplyFixes = async (materialId: string) => {
    const result = results.find(r => r.material_id === materialId);
    if (!result) {
      console.warn('[Linter] 未找到 material:', materialId);
      return;
    }

    const fixableFields = getFixableFields(result);
    console.log('[Linter] 可修复字段:', fixableFields, '问题列表:', result.issues);

    if (fixableFields.length === 0) {
      setSuccessMessage(null);
      setErrorMessage('该文献的问题均为信息提示，无需修复。');
      setTimeout(() => setErrorMessage(null), 3000);
      return;
    }

    setErrorMessage(null);
    setSuccessMessage(null);
    setApplyingFixes(prev => new Set(prev).add(materialId));
    try {
      const baseUrl = getApiBaseUrl();
      console.log('[Linter] 发送修复请求:', { material_id: materialId, fixes: fixableFields });
      const { data } = await axios.post<ApplyFixesResponse>(`${baseUrl}/api/linter/apply-fixes`, {
        material_id: materialId,
        fixes: fixableFields,
        preferred_case: caseStyle,
      }, { timeout: 15000 });

      console.log('[Linter] 修复成功:', data);
      console.log('[Linter] 修复后的结果:', data.result);
      console.log('[Linter] 修复后的问题数:', data.result?.issues?.length);

      // 更新结果：如果修复后没有问题了，从列表中移除
      setResults(prev => {
        console.log('[Linter] 当前结果列表:', prev);
        const updated = prev.map(r => {
          if (r.material_id === materialId) {
            console.log('[Linter] 找到匹配的文献，更新为:', data.result);
            return data.result;
          }
          return r;
        });
        // 过滤掉没有问题的文献
        const filtered = updated.filter(r => {
          const hasIssues = r.issues && r.issues.length > 0;
          console.log(`[Linter] 文献 ${r.material_id}: ${r.issues?.length || 0} 个问题, 保留: ${hasIssues}`);
          return hasIssues;
        });
        console.log('[Linter] 过滤后的结果:', filtered);
        return filtered;
      });

      setSuccessMessage(`已修复 ${fixableFields.length} 个字段`);
      setTimeout(() => setSuccessMessage(null), 3000);

      if (onComplete) onComplete();
    } catch (err) {
      console.error('[Linter] 应用修复失败:', err);
      const axiosError = err as any;
      const detail = axiosError?.response?.data?.detail || axiosError?.message || '未知错误';

      // 如果是"没有可应用的修复"，说明已经是清洁状态
      if (detail.includes('没有可应用') || detail.includes('no fixes')) {
        setSuccessMessage('文献已经是清洁状态，无需修复');
        setTimeout(() => setSuccessMessage(null), 3000);
      } else {
        setErrorMessage(`修复失败: ${detail}`);
      }
    } finally {
      setApplyingFixes(prev => {
        const next = new Set(prev);
        next.delete(materialId);
        return next;
      });
    }
  };

  const problematicResults = results.filter(r => r.issues.length > 0);
  const cleanResults = results.filter(r => r.issues.length === 0);
  const errorCount = results.filter(r => r.has_errors).length;
  const warningCount = results.filter(r => r.has_warnings).length;
  const infoCount = results.filter(r => r.issues.some(issue => issue.severity === 'info')).length;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Sparkles size={13} className="text-primary/70" />
          <span className="text-[11px] font-medium text-foreground/60">元数据 Linter</span>
          {results.length > 0 && (
            <>
              <span className="text-[10px] text-foreground/40">·</span>
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400">
                {cleanResults.length} 清洁
              </span>
              {errorCount > 0 && (
                <>
                  <span className="text-[10px] text-foreground/40">·</span>
                  <span className="text-[10px] text-red-600 dark:text-red-400">
                    {errorCount} 错误
                  </span>
                </>
              )}
              {warningCount > 0 && (
                <>
                  <span className="text-[10px] text-foreground/40">·</span>
                  <span className="text-[10px] text-amber-600 dark:text-amber-400">
                    {warningCount} 警告
                  </span>
                </>
              )}
              <span className="text-[10px] text-foreground/40">·</span>
              <span className="text-[10px] text-foreground/50">
                已检查 {results.length} 条文献
              </span>
              {problematicResults.length > 0 && (
                <button
                  type="button"
                  onClick={() => setExpanded(!expanded)}
                  className="ml-1 text-[10px] text-primary/70 hover:text-primary"
                >
                  {expanded ? '收起' : '展开'}
                </button>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <select
            value={caseStyle}
            onChange={(e) => {
              if (isCaseStyle(e.target.value)) {
                setCaseStyle(e.target.value);
              }
            }}
            disabled={running}
            className="rounded border border-outline-variant/50 bg-surface-low px-1.5 py-0.5 text-[10px] text-foreground disabled:opacity-50"
          >
            <option value="title">Title</option>
            <option value="sentence">Sentence</option>
            <option value="original">原样</option>
          </select>
          <button
            type="button"
            onClick={handleRunLinter}
            disabled={running}
            className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
          >
            {running ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
            {running ? '检查中' : '检查'}
          </button>
        </div>
      </div>

      {errorMessage && (
        <div className="rounded border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-700 dark:border-red-700 dark:bg-red-500/10 dark:text-red-300">
          {errorMessage}
        </div>
      )}

      {successMessage && (
        <div className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-[10px] text-emerald-700 dark:border-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
          ✓ {successMessage}
        </div>
      )}

      {expanded && problematicResults.length > 0 && (
        <div className="space-y-2">
          {problematicResults.map((result) => {
            const isExpanded = expandedMaterial === result.material_id;
            const isApplying = applyingFixes.has(result.material_id);
            const fixableFields = getFixableFields(result);
            const severityIcon = SEVERITY_CONFIG[getResultSeverity(result)];
            const SeverityIcon = severityIcon.icon;

            return (
              <div
                key={result.material_id}
                className="rounded border border-outline-variant/50 bg-surface-lowest"
              >
                <div
                  onClick={() => setExpandedMaterial(isExpanded ? null : result.material_id)}
                  className="flex cursor-pointer items-center justify-between gap-2 px-2 py-1.5 transition-colors hover:bg-surface-low/50"
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    <SeverityIcon size={11} className={severityIcon.color} />
                    <span className="truncate text-[11px] font-medium text-foreground">{result.title}</span>
                    <span className="shrink-0 text-[9px] text-foreground/40">
                      {result.issues.length}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleApplyFixes(result.material_id);
                    }}
                    disabled={isApplying || fixableFields.length === 0}
                    className="inline-flex shrink-0 items-center gap-1 rounded border border-primary/50 bg-primary/5 px-1.5 py-0.5 text-[9px] font-medium text-primary transition-colors hover:bg-primary/15 disabled:opacity-50"
                  >
                    {isApplying && <Loader2 size={9} className="animate-spin" />}
                    {isApplying ? '修复中' : '修复'}
                  </button>
                </div>

                {isExpanded && (
                  <div className="border-t border-outline-variant/30 px-2 py-1.5">
                    <div className="space-y-1">
                      {result.issues.map((issue, idx) => {
                        const config = SEVERITY_CONFIG[issue.severity];
                        const Icon = config.icon;
                        return (
                          <div
                            key={`${issue.field}-${idx}`}
                            className={cn(
                              'rounded border p-1.5 text-[10px]',
                              config.bgColor,
                              config.borderColor,
                            )}
                          >
                            <div className="flex items-start gap-1.5">
                              <Icon size={10} className={cn('shrink-0 mt-0.5', config.color)} />
                              <div className="min-w-0 flex-1">
                                <div className="mb-0.5 flex items-center gap-1.5">
                                  <span className="font-mono text-[9px] text-foreground/50">{issue.field}</span>
                                  <span className={config.color}>{issue.message}</span>
                                </div>
                                {issue.current && (
                                  <div className="mb-0.5">
                                    <span className="text-foreground/40">当前：</span>
                                    <code className="ml-1 text-foreground/60">{issue.current}</code>
                                  </div>
                                )}
                                {issue.suggested && (
                                  <div>
                                    <span className="text-foreground/40">建议：</span>
                                    <code className="ml-1 font-medium text-foreground">{issue.suggested}</code>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}
