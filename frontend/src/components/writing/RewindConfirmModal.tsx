/**
 * RewindConfirmModal — SPEC-SESSION-005 safety gate.
 *
 * Shows:
 *   1. Target checkpoint id + index
 *   2. Warning that `with_files` mode will auto-create `.rollback_snapshots/rewind-<ts>/`
 *   3. Explanation that later turns are archived (not deleted)
 *
 * Plan: docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md §S-5
 */

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, FileWarning, Loader2, ShieldCheck, X } from "lucide-react";
import type { CheckpointMeta } from "@/types/runtime";
import { cn } from "@/lib/utils";

export type RewindMode = "conversation_only" | "with_files";

interface RewindConfirmModalProps {
  isOpen: boolean;
  checkpoint: CheckpointMeta;
  onCancel: () => void;
  onConfirm: (mode: RewindMode) => void | Promise<void>;
  busy?: boolean;
}

export function RewindConfirmModal({
  isOpen,
  checkpoint,
  onCancel,
  onConfirm,
  busy = false,
}: RewindConfirmModalProps) {
  const [mode, setMode] = useState<RewindMode>("conversation_only");

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="rewind-confirm-title"
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 260 }}
            className="w-[520px] max-w-[92vw] rounded-md bg-surface-lowest border border-outline-variant shadow-xl p-6 space-y-4"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-amber-100 text-amber-700 rounded-sm">
                  <AlertTriangle size={18} />
                </div>
                <div>
                  <h3
                    id="rewind-confirm-title"
                    className="font-headline font-semibold text-base text-foreground"
                  >
                    确认回退到检查点
                  </h3>
                  <p className="mt-1 font-body text-[11px] text-foreground/60">
                    即将回退到 checkpoint{" "}
                    <code className="px-1 bg-surface-high rounded text-[10px]">
                      {checkpoint.checkpoint_id.slice(0, 12)}
                    </code>
                    （event{" "}
                    <code className="px-1 bg-surface-high rounded text-[10px]">
                      {checkpoint.event_id.slice(0, 12)}
                    </code>
                    ）
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onCancel}
                disabled={busy}
                className="p-1 rounded-sm text-foreground/40 hover:text-foreground hover:bg-surface-container disabled:opacity-40"
                aria-label="取消"
              >
                <X size={16} />
              </button>
            </div>

            {/* Mode selector */}
            <div className="space-y-2">
              <p className="font-label text-[11px] font-medium text-foreground/70">
                回退范围
              </p>
              <label
                className={cn(
                  "flex items-start gap-3 rounded-sm border px-3 py-2.5 cursor-pointer transition-colors",
                  mode === "conversation_only"
                    ? "border-primary/40 bg-primary/5"
                    : "border-outline-variant hover:border-primary/20",
                )}
              >
                <input
                  type="radio"
                  name="rewind-mode"
                  value="conversation_only"
                  checked={mode === "conversation_only"}
                  onChange={() => setMode("conversation_only")}
                  disabled={busy}
                  className="mt-1"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <ShieldCheck size={12} className="text-emerald-600" />
                    <span className="font-label text-[12px] font-medium text-foreground">
                      仅会话（安全，默认）
                    </span>
                  </div>
                  <p className="mt-1 font-body text-[11px] text-foreground/60 leading-relaxed">
                    只把对话 head 指针回退，不碰工作区文件。稍后 turns 会标记为
                    archived，不会被删除。
                  </p>
                </div>
              </label>

              <label
                className={cn(
                  "flex items-start gap-3 rounded-sm border px-3 py-2.5 cursor-pointer transition-colors",
                  mode === "with_files"
                    ? "border-amber-400 bg-amber-50"
                    : "border-outline-variant hover:border-amber-300",
                )}
              >
                <input
                  type="radio"
                  name="rewind-mode"
                  value="with_files"
                  checked={mode === "with_files"}
                  onChange={() => setMode("with_files")}
                  disabled={busy}
                  className="mt-1"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <FileWarning size={12} className="text-amber-700" />
                    <span className="font-label text-[12px] font-medium text-foreground">
                      会话 + 工作区文件
                    </span>
                  </div>
                  <p className="mt-1 font-body text-[11px] text-foreground/60 leading-relaxed">
                    额外按 checkpoint 时点恢复工作区产物文件。后端会先创建
                    <code className="mx-1 px-1 bg-surface-high rounded text-[10px]">
                      .rollback_snapshots/rewind-&lt;ts&gt;/
                    </code>
                    快照，不会丢失当前状态；但请确认无未同步的草稿。
                  </p>
                </div>
              </label>
            </div>

            {/* Safety reassurance block */}
            <div className="rounded-sm border border-outline-variant/60 bg-surface-low px-3 py-2">
              <p className="font-label text-[10px] text-foreground/50 leading-relaxed">
                此操作 <strong className="text-foreground/70">不可逆</strong>
                （除非再次 fork 或手动 resume archived branch）。
                所有"被丢弃"的 turn 仍在 transcript JSONL 中，可用 fork 找回。
              </p>
            </div>

            {/* Actions */}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onCancel}
                disabled={busy}
                className="px-4 py-2 font-label text-[11px] font-medium text-foreground/60 rounded-sm border border-outline-variant hover:text-foreground hover:bg-surface-container disabled:opacity-40"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void onConfirm(mode)}
                disabled={busy}
                className={cn(
                  "inline-flex items-center gap-1.5 px-4 py-2 rounded-sm font-label text-[11px] font-medium transition-all disabled:opacity-40",
                  mode === "with_files"
                    ? "bg-amber-600 text-white hover:bg-amber-700"
                    : "bg-primary text-primary-foreground hover:bg-primary/90",
                )}
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                {mode === "with_files" ? "回退会话 + 文件" : "回退会话"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
