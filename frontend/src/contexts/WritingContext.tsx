import React, { createContext, useContext, useState, ReactNode } from 'react';

type OutputMode = 'latex' | 'markdown' | 'plain';
type WritingScope = 'selection' | 'section' | 'full_draft';

interface WritingContextType {
  currentProjectId: string;
  setCurrentProjectId: (id: string) => void;
  outputMode: OutputMode;
  setOutputMode: (mode: OutputMode) => void;
  scope: WritingScope;
  setScope: (scope: WritingScope) => void;
}

const WritingContext = createContext<WritingContextType | undefined>(undefined);

export const WritingProvider = ({ children }: { children: ReactNode }) => {
  const [currentProjectId, setCurrentProjectId] = useState<string>('simulation-p1');
  const [outputMode, setOutputMode] = useState<OutputMode>('markdown');
  const [scope, setScope] = useState<WritingScope>('section');

  return (
    <WritingContext.Provider value={{ 
      currentProjectId, setCurrentProjectId,
      outputMode, setOutputMode,
      scope, setScope
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
