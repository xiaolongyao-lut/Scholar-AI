import React, { useState, useRef, useCallback, useEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  side?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
  className?: string;
}

export function Tooltip({ content, children, side = 'top', delay = 300, className }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const tooltipId = useId();
  const triggerRef = useRef<HTMLElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const childProps = children.props as {
    onMouseEnter?: React.MouseEventHandler<HTMLElement>;
    onMouseLeave?: React.MouseEventHandler<HTMLElement>;
    onFocus?: React.FocusEventHandler<HTMLElement>;
    onBlur?: React.FocusEventHandler<HTMLElement>;
    'aria-describedby'?: string;
  };

  const clamp = (value: number, min: number, max: number): number => (
    Math.min(max, Math.max(min, value))
  );

  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const offset = 8;
    const viewportMargin = 16;
    const maxTooltipWidth = Math.min(640, Math.max(280, window.innerWidth - viewportMargin * 2));
    let x = rect.left + rect.width / 2;
    let y = rect.top;

    switch (side) {
      case 'bottom': y = rect.bottom + offset; break;
      case 'left': x = rect.left - offset; y = rect.top + rect.height / 2; break;
      case 'right': x = rect.right + offset; y = rect.top + rect.height / 2; break;
      default: y = rect.top - offset; break;
    }
    if (side === 'top' || side === 'bottom') {
      x = clamp(
        x,
        viewportMargin + maxTooltipWidth / 2,
        window.innerWidth - viewportMargin - maxTooltipWidth / 2,
      );
    } else {
      y = clamp(y, viewportMargin, window.innerHeight - viewportMargin);
    }
    setPos({ x, y });
  }, [side]);

  const show = useCallback(() => {
    timeoutRef.current = setTimeout(() => {
      updatePosition();
      setVisible(true);
    }, delay);
  }, [delay, updatePosition]);

  const hide = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setVisible(false);
  }, []);

  useEffect(() => () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
  }, []);

  useEffect(() => {
    if (!visible) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        hide();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [hide, visible]);

  const translateMap = {
    top: 'translate(-50%, -100%)',
    bottom: 'translate(-50%, 0)',
    left: 'translate(-100%, -50%)',
    right: 'translate(0, -50%)',
  };

  return (
    <>
      {React.cloneElement(children, {
        ref: triggerRef,
        'aria-describedby': visible ? tooltipId : childProps['aria-describedby'],
        onMouseEnter: (event: React.MouseEvent<HTMLElement>) => {
          childProps.onMouseEnter?.(event);
          show();
        },
        onMouseLeave: (event: React.MouseEvent<HTMLElement>) => {
          childProps.onMouseLeave?.(event);
          hide();
        },
        onFocus: (event: React.FocusEvent<HTMLElement>) => {
          childProps.onFocus?.(event);
          show();
        },
        onBlur: (event: React.FocusEvent<HTMLElement>) => {
          childProps.onBlur?.(event);
          hide();
        },
      })}
      {createPortal(
        <AnimatePresence>
          {visible && (
            <motion.div
              id={tooltipId}
              role="tooltip"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.1 }}
              className={cn(
                'fixed z-[100] min-w-72 max-w-[min(40rem,calc(100vw-2rem))] rounded-xl border border-outline-variant/70 bg-surface-highest px-4 py-3 font-label text-xs leading-5 text-foreground shadow-2xl pointer-events-none whitespace-normal break-words',
                className
              )}
              style={{
                left: pos.x,
                top: pos.y,
                maxWidth: 'min(40rem, calc(100vw - 2rem))',
                transform: translateMap[side],
              }}
            >
              {content}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}
