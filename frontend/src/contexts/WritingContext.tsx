import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import type { JobStatus, WritingEvent } from '@/types/runtime';

type OutputMode = 'latex' | 'markdown' | 'plain';
type WritingScope = 'selection' | 'section' | 'full_draft';
type RightDockMode = 'assistant' | 'reference' | 'history' | 'analytics' | 'none';
type ConnectionState = 'online' | 'degraded' | 'offline';
type SessionStatus = 'idle' | 'loading' | 'saving' | 'error';

export interface JobTimelineState {
  jobId: string;
  sessionId: string;
  events: WritingEvent[];
  lastEventId: string | null;
  lastTimestamp: string | null;
  status: JobStatus | null;
  errorMessage: string | null;
}

interface WritingContextType {
  // Data Context
  activeProjectId: string;
  setActiveProjectId: (id: string) => void;
  activeSectionId: string;
  setActiveSectionId: (id: string) => void;
  outputMode: OutputMode;
  setOutputMode: (mode: OutputMode) => void;
  scope: WritingScope;
  setScope: (scope: WritingScope) => void;

  connectionState: ConnectionState;
  setConnectionState: (state: ConnectionState) => void;
  sessionStatus: SessionStatus;
  setSessionStatus: (status: SessionStatus) => void;
  sessionMessage: string | null;
  setSessionMessage: (message: string | null) => void;
  activeJobTimeline: JobTimelineState | null;
  setActiveJobTimeline: (timeline: JobTimelineState | null) => void;
  
  // UI Orchestration
  leftNavCollapsed: boolean;
  setLeftNavCollapsed: (collapsed: boolean) => void;
  rightDockMode: RightDockMode;
  setRightDockMode: (mode: RightDockMode) => void;
  zenMode: boolean;
  setZenMode: (zen: boolean) => void;
  citationDrawerOpen: boolean;
  setCitationDrawerOpen: (open: boolean) => void;
}

const WritingContext = createContext<WritingContextType | undefined>(undefined);

export const WritingProvider = ({ children }: { children: ReactNode }) => {
  // Data State
  const [activeProjectId, setActiveProjectId] = useState<string>('');
  const [activeSectionId, setActiveSectionId] = useState<string>('');
  const [outputMode, setOutputMode] = useState<OutputMode>('markdown');
  const [scope, setScope] = useState<WritingScope>('section');
  const [connectionState, setConnectionState] = useState<ConnectionState>(() => {
    if (typeof navigator === 'undefined') {
      return 'online';
    }

    return navigator.onLine ? 'online' : 'offline';
  });
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('idle');
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);
  const [activeJobTimeline, setActiveJobTimeline] = useState<JobTimelineState | null>(null);
  
  // UI Orchestration State
  const [leftNavCollapsed, setLeftNavCollapsed] = useState<boolean>(false);
  const [rightDockMode, setRightDockMode] = useState<RightDockMode>('assistant');
  const [zenMode, setZenMode] = useState<boolean>(false);
  const [citationDrawerOpen, setCitationDrawerOpen] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const syncConnectionState = () => {
      setConnectionState(navigator.onLine ? 'online' : 'offline');
    };

    syncConnectionState();
    window.addEventListener('online', syncConnectionState);
    window.addEventListener('offline', syncConnectionState);

    return () => {
      window.removeEventListener('online', syncConnectionState);
      window.removeEventListener('offline', syncConnectionState);
    };
  }, []);

  return (
    <WritingContext.Provider value={{ 
      activeProjectId, setActiveProjectId,
      activeSectionId, setActiveSectionId,
      outputMode, setOutputMode,
      scope, setScope,
      connectionState, setConnectionState,
      sessionStatus, setSessionStatus,
      sessionMessage, setSessionMessage,
      activeJobTimeline, setActiveJobTimeline,
      leftNavCollapsed, setLeftNavCollapsed,
      rightDockMode, setRightDockMode,
      zenMode, setZenMode,
      citationDrawerOpen, setCitationDrawerOpen
    }}>
      {children}
    </WritingContext.Provider>
  );
};

export const useWriting = () => {
  const context = useContext(WritingContext);
  if (!context) throw new Error('useWriting must be used within WritingProvider');
  return context;
};
