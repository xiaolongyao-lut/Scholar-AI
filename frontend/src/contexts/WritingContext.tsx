import React, { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import type { JobStatus, WritingEvent } from '@/types/runtime';

type OutputMode = 'latex' | 'markdown' | 'plain';
type WritingScope = 'selection' | 'section' | 'full_draft';
type RightDockMode = 'assistant' | 'reference' | 'history' | 'analytics' | 'none';
type ConnectionState = 'online' | 'degraded' | 'offline';
type SessionStatus = 'idle' | 'loading' | 'saving' | 'error';

const ACTIVE_PROJECT_STORAGE_KEY = 'literature-assistant:active-project-id';
const JOURNAL_STYLE_PROFILE_STORAGE_PREFIX = 'literature-assistant:journal-style-profile:';

export interface JobTimelineState {
  jobId: string;
  sessionId: string;
  events: WritingEvent[];
  lastEventId: string | null;
  lastTimestamp: string | null;
  lastSequence: number | null;
  status: JobStatus | null;
  errorMessage: string | null;
}

interface WritingContextType {
  // Data Context
  activeProjectId: string;
  setActiveProjectId: (id: string) => void;
  activeJournalStyleProfileId: string;
  setActiveJournalStyleProfileId: (id: string) => void;
  projectDataVersion: number;
  markProjectDataChanged: () => void;
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

function getLocalStorage(): Storage | null {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Reads the last active project id from browser storage.
 *
 * Returns an empty string when storage is unavailable, blocked, or contains a
 * non-string value so route-level project selection can still recover.
 */
function readStoredActiveProjectId(): string {
  const storage = getLocalStorage();
  if (!storage) {
    return '';
  }

  try {
    return (storage.getItem(ACTIVE_PROJECT_STORAGE_KEY) ?? '').trim();
  } catch {
    return '';
  }
}

function writeStoredActiveProjectId(projectId: string): void {
  const storage = getLocalStorage();
  if (!storage) {
    return;
  }

  try {
    if (!projectId) {
      storage.removeItem(ACTIVE_PROJECT_STORAGE_KEY);
      return;
    }

    storage.setItem(ACTIVE_PROJECT_STORAGE_KEY, projectId);
  } catch {
    // Storage failures must not block project switching.
  }
}

function readStoredJournalStyleProfileId(projectId: string): string {
  const normalizedProjectId = projectId.trim();
  if (!normalizedProjectId) {
    return '';
  }
  const storage = getLocalStorage();
  if (!storage) {
    return '';
  }

  try {
    return (storage.getItem(`${JOURNAL_STYLE_PROFILE_STORAGE_PREFIX}${normalizedProjectId}`) ?? '').trim();
  } catch {
    return '';
  }
}

function writeStoredJournalStyleProfileId(projectId: string, profileId: string): void {
  const normalizedProjectId = projectId.trim();
  const storage = getLocalStorage();
  if (!normalizedProjectId || !storage) {
    return;
  }

  try {
    const key = `${JOURNAL_STYLE_PROFILE_STORAGE_PREFIX}${normalizedProjectId}`;
    const normalizedProfileId = profileId.trim();
    if (!normalizedProfileId) {
      storage.removeItem(key);
      return;
    }
    storage.setItem(key, normalizedProfileId);
  } catch {
    // Storage failures must not block manuscript export.
  }
}

export const WritingProvider = ({ children }: { children: ReactNode }) => {
  // Data State
  const [activeProjectId, setActiveProjectIdState] = useState<string>(() => readStoredActiveProjectId());
  const [activeJournalStyleProfileId, setActiveJournalStyleProfileIdState] = useState<string>('');
  const [projectDataVersion, setProjectDataVersion] = useState<number>(0);
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

  const setActiveProjectId = useCallback((id: string) => {
    if (typeof id !== 'string') {
      throw new Error('activeProjectId must be a string');
    }

    const normalized = id.trim();
    setActiveProjectIdState(normalized);
    writeStoredActiveProjectId(normalized);
  }, []);

  const setActiveJournalStyleProfileId = useCallback((id: string) => {
    if (typeof id !== 'string') {
      throw new Error('activeJournalStyleProfileId must be a string');
    }

    const normalized = id.trim();
    setActiveJournalStyleProfileIdState(normalized);
    writeStoredJournalStyleProfileId(activeProjectId, normalized);
  }, [activeProjectId]);

  const markProjectDataChanged = useCallback(() => {
    setProjectDataVersion(version => version + 1);
  }, []);

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

  useEffect(() => {
    setActiveJournalStyleProfileIdState(readStoredJournalStyleProfileId(activeProjectId));
  }, [activeProjectId]);

  return (
    <WritingContext.Provider value={{ 
      activeProjectId, setActiveProjectId,
      activeJournalStyleProfileId, setActiveJournalStyleProfileId,
      projectDataVersion, markProjectDataChanged,
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
