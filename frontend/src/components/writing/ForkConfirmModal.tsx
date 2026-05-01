import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { GitBranch, Loader2, X, Info } from "lucide-react";
import type { CheckpointMeta } from "@/types/runtime";

interface ForkConfirmModalProps {
  isOpen: boolean;
  checkpoint: CheckpointMeta;
  onCancel: () => void;
  onConfirm: () => void | Promise<void>;
  busy?: boolean;
}

export function ForkConfirmModal({
  isOpen,
  checkpoint,
  onCancel,
  onConfirm,
  busy = false,
}: ForkConfirmModalProps) {
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
          aria-labelledby="fork-confirm-title"
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 260 }}
            className="w-[480px] max-w-[92vw] rounded-md bg-surface-lowest border border-outline-variant shadow-xl p-6 space-y-4"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-sm">
                  <GitBranch size={18} />
                </div>
                <div>
                  <h3
                    id="fork-confirm-title"
                    className="font-headline font-semibold text-base text-foreground"
                  >
                    从检查点分叉
                  </h3>
                  <p className="mt-1 font-body text-[11px] text-foreground/60">
                    即将从 checkpoint{" "}
                    <code className="px-1 bg-surface-high rounded text-[10px]">
                      {checkpoint.checkpoint_id.slice(0, 12)}
                    </code>{" "}
                    分叉出一个全新的并行会话。
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

            <div className="rounded-sm border border-outline-variant/60 bg-surface-low px-3 py-2 flex items-start gap-2">
              <Info size={14} className="text-primary/60 mt-0.5" />
              <p className="font-label text-[10px] text-foreground/50 leading-relaxed">
                分叉操作会克隆当前检查点之前的全部历史，但之后产生的对话将独立存储，互不影响。这非常适合尝试不同的提问方向。
              </p>
            </div>

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
                onClick={() => void onConfirm()}
                disabled={busy}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-sm bg-primary text-primary-foreground font-label text-[11px] font-medium hover:bg-primary/90 transition-all disabled:opacity-40"
              >
                {busy && <Loader2 size={12} className="animate-spin" />}
                创建分叉会话
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
