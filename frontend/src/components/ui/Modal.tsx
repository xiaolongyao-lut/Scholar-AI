import React, { useEffect, useCallback, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/contexts/I18nContext';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
  showCloseButton?: boolean;
  closeOnBackdrop?: boolean;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  role?: 'dialog' | 'alertdialog';
  labelledBy?: string;
  describedBy?: string;
  initialFocusRef?: RefObject<HTMLElement>;
}

const sizeMap = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

export function Modal({
  open,
  onClose,
  children,
  className,
  showCloseButton = true,
  closeOnBackdrop = true,
  size = 'md',
  role = 'dialog',
  labelledBy,
  describedBy,
  initialFocusRef,
}: ModalProps) {
  const { t } = useI18n();
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
      window.setTimeout(() => {
        initialFocusRef?.current?.focus();
      }, 0);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, handleKeyDown, initialFocusRef]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm bg-black/40"
          onClick={closeOnBackdrop ? onClose : undefined}
          role={role}
          aria-modal="true"
          aria-labelledby={labelledBy}
          aria-describedby={describedBy}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className={cn(
              'w-full bg-surface-lowest rounded-lg shadow-2xl border border-outline-variant flex flex-col relative',
              sizeMap[size],
              className
            )}
            onClick={e => e.stopPropagation()}
          >
            {showCloseButton && (
              <button
                type="button"
                onClick={onClose}
                className="absolute top-4 right-4 p-1.5 text-foreground/40 hover:text-foreground rounded-sm hover:bg-surface-high transition-colors z-10"
                aria-label={t('common.close')}
              >
                <X size={18} />
              </button>
            )}
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}

export function ModalHeader({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('px-6 pt-6 pb-4 border-b border-outline-variant', className)}>
      {children}
    </div>
  );
}

export function ModalBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('px-6 py-5 overflow-y-auto custom-scrollbar', className)}>
      {children}
    </div>
  );
}

export function ModalFooter({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('px-6 py-4 border-t border-outline-variant flex items-center justify-end gap-3', className)}>
      {children}
    </div>
  );
}
