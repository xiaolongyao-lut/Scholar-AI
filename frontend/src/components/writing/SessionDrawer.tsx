/**
 * SessionDrawer — conversation persistence UI for the Workbench.
 * Backend contract: routers/runtime_router.py
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Clock,
  GitBranch,
  History,
  Loader2,
  RotateCcw,
  Trash2,
  X,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getSessionApi } from "@/services/sessionApi";
import type {
  SessionSummary,
  TimelineEvent,
  CheckpointMeta,
  ResumeSessionResult,
} from "@/types/runtime";
import {
  sortAndLimitSessions,
  sessionPreviewText,
  isForkedSession,
  formatTimelineEventLabel,
  formatTimelineEventPreview,
  formatSessionDrawerError,
  resolveNextCursor,
  formatRelativeTimestamp,
} from "./sessionDrawerHelpers";
import { RewindConfirmModal } from "./RewindConfirmModal";
import { useSessionPersistence } from "@/hooks/useSessionPersistence";

interface SessionDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  /** Current workspace binding — used to scope the session list. */
  workspaceRoot?: string;
  workspaceKey?: string;
  /** Called after a successful resume so Workbench can pick up the new head. */
  onSessionResumed?: (result: ResumeSessionResult) => void;
  /** Called after a branch is created; parent switches to the returned session. */
  onSessionForked?: (result: ResumeSessionResult) => void;
  /** Called after rollback preview is applied. */
  onSessionRewound?: (result: ResumeSessionResult) => void;
}

type LoadState = "idle" | "loading" | "error";

const TIMELINE_PAGE_SIZE = 50;
const SESSION_LIMIT = 10;

const kindBadgeClass: Record<string, string> = {
  user: "bg-primary/10 text-primary border-primary/20",
  assistant: "bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-700/40",
  tool_call: "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-700/40",
  tool_result: "bg-sky-100 text-sky-700 border-sky-200 dark:bg-sky-500/15 dark:text-sky-300 dark:border-sky-700/40",
  checkpoint: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-500/15 dark:text-purple-300 dark:border-purple-700/40",
  other: "bg-surface-high text-foreground/50 border-outline-variant",
};

import { ForkConfirmModal } from "./ForkConfirmModal";
import { useToast } from "@/components/ui/Toast";
import { useI18n } from "@/contexts/I18nContext";

export function SessionDrawer({
  isOpen,
  onClose,
  workspaceRoot,
  workspaceKey,
  onSessionResumed,
  onSessionForked,
  onSessionRewound,
}: SessionDrawerProps) {
  const { t: _t } = useI18n();
  const { toast } = useToast();
  const { resume, fork, rewind } = useSessionPersistence();
  const api = useMemo(() => getSessionApi(), []);

  // ---- Session list state -------------------------------------------------
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [listState, setListState] = useState<LoadState>("idle");
  const [listError, setListError] = useState<string | null>(null);

  // ---- Expanded session state --------------------------------------------
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null);
  const [timelineState, setTimelineState] = useState<LoadState>("idle");
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [checkpoints, setCheckpoints] = useState<CheckpointMeta[]>([]);

  // ---- Action state -------------------------------------------------------
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [forkTarget, setForkTarget] = useState<{
    sessionId: string;
    checkpoint: CheckpointMeta;
  } | null>(null);
  const [rewindTarget, setRewindTarget] = useState<{
    sessionId: string;
    checkpoint: CheckpointMeta;
  } | null>(null);
  const [lastRewindToast, setLastRewindToast] = useState<{
    snapshot?: string;
    archivedCount?: number;
    mode: "conversation_only" | "with_files";
  } | null>(null);

  const visibleSessions = useMemo(
    () => sortAndLimitSessions(sessions, SESSION_LIMIT),
    [sessions],
  );

  const resetTimelineState = useCallback(() => {
    setTimelineEvents([]);
    setTimelineCursor(null);
    setTimelineState("idle");
    setTimelineError(null);
    setCheckpoints([]);
  }, []);

  // ---- Load list ---------------------------------------------------------
  const loadSessions = useCallback(async () => {
    setListState("loading");
    setListError(null);
    try {
      const result = await api.listSessions({
        workspace_root: workspaceRoot,
        workspace_key: workspaceKey,
      });
      setSessions(result);
      setListState("idle");
    } catch (err) {
      setListError(formatSessionDrawerError(err, "无法加载会话，请稍后重试。"));
      setListState("error");
    }
  }, [api, workspaceRoot, workspaceKey]);

  useEffect(() => {
    if (isOpen) {
      loadSessions();
    } else {
      setExpandedId(null);
      resetTimelineState();
    }
  }, [isOpen, loadSessions, resetTimelineState]);

  // ---- Expand / load timeline --------------------------------------------
  const loadTimelineFirstPage = useCallback(
    async (sessionId: string) => {
      setTimelineState("loading");
      setTimelineError(null);
      try {
        const [page, cps] = await Promise.all([
          api.getTimeline(sessionId, { limit: TIMELINE_PAGE_SIZE }),
          api.listCheckpoints(sessionId),
        ]);
        setTimelineEvents(page.items);
        setTimelineCursor(resolveNextCursor(page.items, page.next_cursor));
        setCheckpoints(cps);
        setTimelineState("idle");
      } catch (err) {
        setTimelineError(formatSessionDrawerError(err, "无法加载时间线，请稍后重试。"));
        setTimelineState("error");
      }
    },
    [api],
  );

  const loadTimelineNextPage = useCallback(async () => {
    if (!expandedId || !timelineCursor) return;
    setTimelineState("loading");
    try {
      const page = await api.getTimeline(expandedId, {
        after_event_id: timelineCursor,
        limit: TIMELINE_PAGE_SIZE,
      });
      setTimelineEvents((prev) => [...prev, ...page.items]);
      setTimelineCursor(resolveNextCursor(page.items, page.next_cursor));
      setTimelineState("idle");
    } catch (err) {
      setTimelineError(formatSessionDrawerError(err, "无法加载更多时间线，请稍后重试。"));
      setTimelineState("error");
    }
  }, [api, expandedId, timelineCursor]);

  const toggleExpand = useCallback(
    async (sessionId: string) => {
      if (expandedId === sessionId) {
        setExpandedId(null);
        resetTimelineState();
        return;
      }
      setExpandedId(sessionId);
      resetTimelineState();
      await loadTimelineFirstPage(sessionId);
    },
    [expandedId, loadTimelineFirstPage, resetTimelineState],
  );

  // ---- Actions: resume / fork / rewind -----------------------------------
  const handleResume = useCallback(
    async (sessionId: string) => {
      setBusyAction(`resume:${sessionId}`);
      try {
        const result = await resume(sessionId);
        onSessionResumed?.(result);
        onClose();
      } catch {
        // hook handles toast
      } finally {
        setBusyAction(null);
      }
    },
    [resume, onSessionResumed, onClose],
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      const target = sessionPreviewText(
        sessions.find((session) => session.session_id === sessionId) ?? {
          session_id: sessionId,
          mode: "prompt",
          created_at: "",
          settings: {},
          tags: [],
          metadata: {},
        },
      );
      if (!window.confirm(`确认删除会话「${target}」？此操作只删除本机会话记录。`)) {
        return;
      }
      setBusyAction(`delete:${sessionId}`);
      try {
        await api.deleteSession(sessionId);
        setSessions((prev) => prev.filter((session) => session.session_id !== sessionId));
        if (expandedId === sessionId) {
          setExpandedId(null);
          resetTimelineState();
        }
        toast("会话已删除", "success");
      } catch (err) {
        toast(formatSessionDrawerError(err, "删除会话失败，请稍后重试。"), "error");
      } finally {
        setBusyAction(null);
      }
    },
    [api, expandedId, resetTimelineState, sessions, setSessions, toast],
  );

  const requestFork = useCallback(
    (sessionId: string, checkpoint: CheckpointMeta) => {
      setForkTarget({ sessionId, checkpoint });
    },
    [],
  );

  const handleForkConfirm = useCallback(async () => {
    if (!forkTarget) return;
    const { sessionId, checkpoint } = forkTarget;
    setBusyAction(`fork:${checkpoint.checkpoint_id}`);
    try {
      const result = await fork(sessionId, checkpoint);
      onSessionForked?.(result);
      setForkTarget(null);
      await loadSessions();
    } catch {
      // hook handles toast
    } finally {
      setBusyAction(null);
    }
  }, [fork, forkTarget, onSessionForked, loadSessions]);

  const requestRewind = useCallback(
    (sessionId: string, checkpoint: CheckpointMeta) => {
      setRewindTarget({ sessionId, checkpoint });
    },
    [],
  );

  const handleRewindConfirm = useCallback(
    async (mode: "conversation_only" | "with_files") => {
      if (!rewindTarget) return;
      const { sessionId, checkpoint } = rewindTarget;
      setBusyAction(`rewind:${checkpoint.checkpoint_id}`);
      try {
        const result = await rewind(sessionId, checkpoint, mode);
        onSessionRewound?.(result);
        
        // Surface backend-returned snapshot path / archived turn count.
        const meta = (result.session?.metadata ?? {}) as Record<string, unknown>;
        const snapshot =
          typeof meta.rollback_snapshot_path === "string"
            ? (meta.rollback_snapshot_path as string)
            : undefined;
        const archivedCount =
          typeof meta.archived_turns_count === "number"
            ? (meta.archived_turns_count as number)
            : undefined;
        setLastRewindToast({ snapshot, archivedCount, mode });
        setRewindTarget(null);
        if (expandedId === sessionId) {
          await loadTimelineFirstPage(sessionId);
        }
      } catch {
        // hook handles toast
      } finally {
        setBusyAction(null);
      }
    },
    [rewind, rewindTarget, onSessionRewound, expandedId, loadTimelineFirstPage],
  );

  // ---- Render ------------------------------------------------------------
  return (
    <>
      <AnimatePresence>
        {isOpen && (
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            id="session-drawer"
            role="complementary"
            aria-labelledby="session-drawer-title"
            className="absolute right-0 top-0 bottom-0 w-[480px] bg-surface-lowest border-l border-outline-variant z-50 shadow-[-8px_0_24px_rgba(0,0,0,0.06)] flex flex-col"
          >
            {/* Header */}
            <div className="p-6 border-b border-outline-variant flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-sm">
                  <History size={20} />
                </div>
                <h3
                  id="session-drawer-title"
                  className="font-headline font-semibold text-base text-foreground"
                >
                  会话历史
                </h3>
              </div>
              <button
                onClick={onClose}
                aria-label="关闭会话抽屉"
                className="p-2 hover:bg-surface-container rounded-sm transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            {/* Rewind success toast */}
            {lastRewindToast && (
              <div className="mx-4 mt-3 rounded-sm border border-border bg-surface-container px-3 py-2">
                <div className="flex items-start gap-2">
                  <div className="flex-1">
                    <p className="font-label text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                      回退完成（
                      {lastRewindToast.mode === "with_files"
                        ? "会话 + 文件"
                        : "仅会话"}
                      ）
                    </p>
                    {typeof lastRewindToast.archivedCount === "number" && (
                      <p className="mt-1 font-body text-[10px] text-foreground/70">
                        已归档 {lastRewindToast.archivedCount} 条后续记录，未删除，可通过分叉找回。
                      </p>
                    )}
                    {lastRewindToast.snapshot && (
                      <p className="mt-1 font-body text-[10px] text-foreground/70 break-all">
                        已创建本地回退快照；需要恢复时请从本机回滚记录中选择。
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setLastRewindToast(null)}
                    aria-label="关闭提示"
                    className="p-0.5 text-foreground/50 hover:text-foreground"
                  >
                    <X size={12} />
                  </button>
                </div>
              </div>
            )}

            {/* Body */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-3">
              {listState === "loading" && sessions.length === 0 && (
                <div className="flex items-center gap-2 text-foreground/40 px-2 py-6">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="font-label text-xs">加载会话中…</span>
                </div>
              )}

              {listState === "error" && (
                <div className="rounded-sm border border-red-200 bg-red-50 px-4 py-3">
                  <div className="flex items-center gap-2 text-red-700">
                    <AlertTriangle size={14} />
                    <span className="font-label text-[11px] font-medium">
                      无法加载会话
                    </span>
                  </div>
                  <p className="mt-1 font-body text-[11px] text-red-700/80">
                    {listError ?? "未知错误"}
                  </p>
                  <button
                    type="button"
                    onClick={loadSessions}
                    className="mt-2 font-label text-[10px] text-red-700 underline"
                  >
                    重试
                  </button>
                </div>
              )}

              {listState === "idle" && visibleSessions.length === 0 && (
                <div className="rounded-sm border border-dashed border-outline-variant bg-surface-low px-5 py-6 text-center">
                  <p className="font-headline text-sm font-semibold text-foreground">
                    当前工作区暂无会话
                  </p>
                  <p className="mt-2 font-body text-[11px] leading-5 text-foreground/50">
                    发起一次对话后，会话会自动落盘到
                    <code className="mx-1 px-1 bg-surface-high rounded text-[10px]">
                          本机会话库
                    </code>
                    并出现在这里。
                  </p>
                </div>
              )}

              {visibleSessions.map((session) => {
                const sid = session.session_id;
                const isExpanded = expandedId === sid;
                const forked = isForkedSession(session);
                const parent =
                  typeof session.metadata?.parent_session_id === "string"
                    ? (session.metadata.parent_session_id as string)
                    : null;

                return (
                  <div
                    key={sid}
                    className={cn(
                      "glass-card rounded-sm border transition-all",
                      isExpanded
                        ? "border-primary/30 bg-primary/5"
                        : "border-transparent hover:border-primary/20",
                    )}
                  >
                    {/* Row header */}
                    <div className="flex items-start gap-2 p-4">
                      <button
                        type="button"
                        onClick={() => toggleExpand(sid)}
                        className="mt-1 p-0.5 rounded-sm text-foreground/40 hover:text-primary hover:bg-surface-container transition-colors"
                        aria-label={isExpanded ? "折叠时间线" : "展开时间线"}
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? (
                          <ChevronDown size={14} />
                        ) : (
                          <ChevronRight size={14} />
                        )}
                      </button>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-label text-[10px] font-medium px-1.5 py-0.5 bg-surface-high rounded-sm text-foreground/70">
                            会话记录
                          </span>
                          {forked && (
                            <span
                              className="inline-flex items-center gap-1 font-label text-[9px] font-medium px-1.5 py-0.5 bg-violet-100 text-violet-700 border border-violet-200 rounded-sm"
                              title={parent ? "从早前会话分叉而来" : "分叉会话"}
                            >
                              <GitBranch size={9} />
                              分叉
                            </span>
                          )}
                          <span className="ml-auto flex items-center gap-1 font-label text-[10px] text-foreground/40">
                            <Clock size={10} />
                            {formatRelativeTimestamp(session.created_at)}
                          </span>
                        </div>
                        <p className="font-body text-[12px] text-foreground/70 leading-snug line-clamp-2">
                          {sessionPreviewText(session)}
                        </p>
                      </div>
                    </div>

                    {/* Action row */}
                    <div className="px-4 pb-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => handleResume(sid)}
                        disabled={busyAction === `resume:${sid}` || busyAction === `delete:${sid}`}
                        className="inline-flex items-center gap-1.5 rounded-sm bg-primary px-3 py-1 font-label text-[10px] font-medium text-primary-foreground transition-all hover:bg-primary/90 disabled:opacity-40"
                        aria-label="恢复该会话"
                      >
                        {busyAction === `resume:${sid}` ? (
                          <Loader2 size={10} className="animate-spin" />
                        ) : (
                          <RotateCcw size={10} />
                        )}
                        恢复
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteSession(sid)}
                        disabled={busyAction === `delete:${sid}`}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-red-200 bg-red-50 px-3 py-1 font-label text-[10px] font-medium text-red-700 transition-all hover:bg-red-100 disabled:opacity-40 dark:border-red-700/40 dark:bg-red-500/15 dark:text-red-300"
                        aria-label="删除该会话"
                        title="删除该会话"
                      >
                        {busyAction === `delete:${sid}` ? (
                          <Loader2 size={10} className="animate-spin" />
                        ) : (
                          <Trash2 size={10} />
                        )}
                        删除
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleExpand(sid)}
                        disabled={busyAction === `delete:${sid}`}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-outline-variant bg-surface-lowest px-3 py-1 font-label text-[10px] font-medium text-foreground/60 transition-all hover:text-foreground"
                      >
                        {isExpanded ? "隐藏时间线" : "查看时间线"}
                      </button>
                    </div>

                    {/* Expanded timeline */}
                    {isExpanded && (
                      <div className="border-t border-outline-variant/60 bg-surface-low/50 p-3 space-y-2">
                        {timelineState === "loading" &&
                          timelineEvents.length === 0 && (
                            <div className="flex items-center gap-2 text-foreground/40 py-2 px-1">
                              <Loader2 size={12} className="animate-spin" />
                              <span className="font-label text-[10px]">
                                加载时间线…
                              </span>
                            </div>
                          )}

                        {timelineState === "error" && (
                          <div className="rounded-sm border border-red-200 bg-red-50 px-3 py-2">
                            <p className="font-label text-[10px] text-red-700">
                              时间线加载失败：{timelineError ?? "未知错误"}
                            </p>
                          </div>
                        )}

                        {timelineEvents.length === 0 &&
                          timelineState === "idle" && (
                            <p className="font-label text-[10px] text-foreground/40 px-1 py-2">
                              该会话暂无事件。
                            </p>
                          )}

                        {timelineEvents.map((event) => {
                          const kind = event.event_kind;
                          const badgeClass =
                            kindBadgeClass[kind] ?? kindBadgeClass.other;
                          const cp = checkpoints.find(
                            (c) => c.event_id === event.event_id,
                          );
                          return (
                            <div
                              key={event.event_id}
                              className="rounded-sm border border-outline-variant/50 bg-surface-lowest px-3 py-2"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span
                                  className={cn(
                                    "font-label text-[9px] font-medium px-1.5 py-0.5 rounded-sm border",
                                    badgeClass,
                                  )}
                                >
                                  {formatTimelineEventLabel(event)}
                                </span>
                                <span className="font-label text-[9px] text-foreground/40">
                                  {formatRelativeTimestamp(event.timestamp)}
                                </span>
                                {event.ref && (
                                  <span
                                    className="font-label text-[9px] text-foreground/40"
                                    title="正文已安全存放在本地记录中"
                                  >
                                    有正文
                                  </span>
                                )}
                                {cp && (
                                  <div className="ml-auto flex gap-1">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        requestFork(sid, cp)
                                      }
                                      disabled={
                                        busyAction ===
                                        `fork:${cp.checkpoint_id}`
                                      }
                                      className="inline-flex items-center gap-1 rounded-sm border border-outline-variant bg-surface-lowest px-1.5 py-0.5 font-label text-[9px] text-foreground/60 hover:text-primary hover:border-primary/30 disabled:opacity-40"
                                      title="从该检查点分叉"
                                      aria-label="从该检查点分叉"
                                    >
                                      <GitBranch size={9} />
                                      分叉
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => requestRewind(sid, cp)}
                                      disabled={
                                        busyAction ===
                                        `rewind:${cp.checkpoint_id}`
                                      }
                                      className="inline-flex items-center gap-1 rounded-sm border border-amber-300 bg-amber-50 px-1.5 py-0.5 font-label text-[9px] text-amber-800 hover:bg-amber-100 disabled:opacity-40"
                                      title="回退到该检查点"
                                      aria-label="回退到该检查点"
                                    >
                                      <RotateCcw size={9} />
                                      回退
                                    </button>
                                  </div>
                                )}
                              </div>
                              <p className="font-body text-[11px] text-foreground/60 leading-snug line-clamp-2">
                                {formatTimelineEventPreview(event)}
                              </p>
                            </div>
                          );
                        })}

                        {timelineCursor && (
                          <button
                            type="button"
                            onClick={loadTimelineNextPage}
                            disabled={timelineState === "loading"}
                            className="w-full py-2 font-label text-[10px] text-foreground/50 hover:text-primary border border-dashed border-outline-variant rounded-sm disabled:opacity-40"
                          >
                            {timelineState === "loading"
                              ? "加载中…"
                              : `加载下 ${TIMELINE_PAGE_SIZE} 条`}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Fork confirm */}
      {forkTarget && (
        <ForkConfirmModal
          isOpen={true}
          checkpoint={forkTarget.checkpoint}
          onCancel={() => setForkTarget(null)}
          onConfirm={handleForkConfirm}
          busy={busyAction === `fork:${forkTarget.checkpoint.checkpoint_id}`}
        />
      )}

      {/* Rewind confirm — rendered outside aside so it sits above drawer */}
      {rewindTarget && (
        <RewindConfirmModal
          isOpen={true}
          checkpoint={rewindTarget.checkpoint}
          onCancel={() => setRewindTarget(null)}
          onConfirm={handleRewindConfirm}
          busy={
            busyAction === `rewind:${rewindTarget.checkpoint.checkpoint_id}`
          }
        />
      )}
    </>
  );
}
