import React, { Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { WritingProvider } from './contexts/WritingContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { PdfTabsProvider } from './contexts/PdfTabsContext';
import { DiscussionProvider } from './contexts/DiscussionContext';
import { SmartReadProvider } from './contexts/SmartReadContext';
import { ToastProvider } from './components/ui/Toast';
import { CommandPalette } from './components/ui/CommandPalette';
import { McpPendingCallPoller } from './components/mcp/McpPendingCallPoller';
import { ErrorBoundary } from './components/common/ErrorBoundary';

// Route-level lazy imports keep the initial shell small.
const Workbench = React.lazy(() => import('./pages/Workbench').then(m => ({ default: m.Workbench })));
const Projects = React.lazy(() => import('./pages/Projects').then(m => ({ default: m.Projects })));
const KnowledgeBase = React.lazy(() => import('./pages/KnowledgeBase').then(m => ({ default: m.KnowledgeBase })));
const KnowledgeDeposits = React.lazy(() => import('./pages/KnowledgeDeposits').then(m => ({ default: m.KnowledgeDeposits })));
const SettingsPage = React.lazy(() => import('./pages/Settings').then(m => ({ default: m.SettingsPage })));
const VolumeAnalysis = React.lazy(() => import('./pages/VolumeAnalysis').then(m => ({ default: m.VolumeAnalysis })));
const Jobs = React.lazy(() => import('./pages/Jobs').then(m => ({ default: m.Jobs })));
const DraftStudio = React.lazy(() => import('./components/DraftStudio').then(m => ({ default: m.DraftStudio })));
const Dialog = React.lazy(() => import('./pages/Dialog').then(m => ({ default: m.Dialog })));
const ResearchWorkbench = React.lazy(() => import('./pages/ResearchWorkbench').then(m => ({ default: m.ResearchWorkbench })));
const WorkbenchWiki = React.lazy(() => import('./pages/WorkbenchObjectAdapters').then(m => ({ default: m.WorkbenchWiki })));
const WritingOverview = React.lazy(() => import('./pages/writing/WritingOverview').then(m => ({ default: m.WritingOverview })));
const OutlineManager = React.lazy(() => import('./pages/writing/OutlineManager').then(m => ({ default: m.OutlineManager })));
const SourcesCitations = React.lazy(() => import('./pages/writing/SourcesCitations').then(m => ({ default: m.SourcesCitations })));
const FiguresTables = React.lazy(() => import('./pages/writing/FiguresTables').then(m => ({ default: m.FiguresTables })));
const ReviewerSubmission = React.lazy(() => import('./pages/writing/ReviewerSubmission').then(m => ({ default: m.ReviewerSubmission })));

const LazyFallback = () => (
  <div className="h-full flex items-center justify-center bg-background">
    <div className="flex flex-col items-center gap-3">
      <div className="h-8 w-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      <p className="font-label text-xs text-foreground/40">加载中…</p>
    </div>
  </div>
);

const App = () => {
  return (
    <ErrorBoundary fallbackTitle="应用发生异常，请刷新页面或返回首页">
      <ThemeProvider>
        <WritingProvider>
          <PdfTabsProvider>
            <DiscussionProvider>
              <SmartReadProvider>
              <ToastProvider>
              <Router>
                <MainLayout>
                  <Suspense fallback={<LazyFallback />}>
                    <Routes>
                      {/* Home */}
                      <Route path="/" element={<Navigate to="/dialog" replace />} />

                      {/* Writing group */}
                      <Route path="/writing" element={<WritingOverview />} />
                      <Route path="/writing/draft" element={<DraftStudio />} />
                      <Route path="/writing/outline" element={<OutlineManager />} />
                      <Route path="/writing/sources" element={<SourcesCitations />} />
                      <Route path="/writing/figures" element={<FiguresTables />} />
                      <Route path="/writing/reviewer" element={<ReviewerSubmission />} />

                      {/* Standalone pages */}
                      <Route path="/knowledge" element={<KnowledgeBase />} />
                      <Route path="/library" element={<Workbench />} />
                      <Route path="/wiki" element={<KnowledgeDeposits />} />
                      <Route path="/projects" element={<Projects />} />
                      <Route path="/volume" element={<VolumeAnalysis />} />
                      <Route path="/inspiration" element={<Navigate to="/dialog" replace />} />
                      <Route path="/chat" element={<Navigate to="/dialog" replace />} />
                      <Route path="/intelligent-chat" element={<Navigate to="/dialog" replace />} />
                      <Route path="/dialog" element={<Dialog />} />
                      <Route path="/discussion" element={<Navigate to="/dialog?mode=discussion" replace />} />
                      {/* ResearchWorkbench — gated by VITE_FLAG_RESEARCH_WORKBENCH; otherwise
                          the component itself redirects to /knowledge. */}
                      <Route path="/workbench/paper/:materialId" element={<ResearchWorkbench />} />
                      <Route path="/workbench/discussion" element={<Navigate to="/dialog?mode=discussion" replace />} />
                      <Route path="/workbench/wiki" element={<WorkbenchWiki />} />
                      <Route path="/workbench/inspiration" element={<Navigate to="/dialog" replace />} />
                      <Route path="/jobs" element={<Jobs />} />
                      <Route path="/evolution" element={<KnowledgeDeposits />} />
                      <Route path="/settings" element={<SettingsPage />} />

                      {/* Fallback */}
                      <Route path="*" element={<Navigate to="/dialog" replace />} />
                    </Routes>
                  </Suspense>
                </MainLayout>
                <CommandPalette />
                <McpPendingCallPoller />
              </Router>
            </ToastProvider>
            </SmartReadProvider>
            </DiscussionProvider>
          </PdfTabsProvider>
        </WritingProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
};

export default App;
