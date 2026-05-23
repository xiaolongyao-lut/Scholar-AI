import React, { Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { WritingProvider } from './contexts/WritingContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { PdfTabsProvider } from './contexts/PdfTabsContext';
import { DiscussionProvider } from './contexts/DiscussionContext';
import { ToastProvider } from './components/ui/Toast';
import { CommandPalette } from './components/ui/CommandPalette';
import { McpPendingCallPoller } from './components/mcp/McpPendingCallPoller';
import { ErrorBoundary } from './components/common/ErrorBoundary';

// Route-level lazy imports for code splitting (TASK-181)
const Workbench = React.lazy(() => import('./pages/Workbench').then(m => ({ default: m.Workbench })));
const Projects = React.lazy(() => import('./pages/Projects').then(m => ({ default: m.Projects })));
const KnowledgeBase = React.lazy(() => import('./pages/KnowledgeBase').then(m => ({ default: m.KnowledgeBase })));
const WikiWorkbench = React.lazy(() => import('./pages/WikiWorkbench').then(m => ({ default: m.WikiWorkbench })));
const SettingsPage = React.lazy(() => import('./pages/Settings').then(m => ({ default: m.SettingsPage })));
const VolumeAnalysis = React.lazy(() => import('./pages/VolumeAnalysis').then(m => ({ default: m.VolumeAnalysis })));
const Jobs = React.lazy(() => import('./pages/Jobs').then(m => ({ default: m.Jobs })));
  // Standalone /inspiration is folded into Dialog inspiration mode.
const DraftStudio = React.lazy(() => import('./components/DraftStudio').then(m => ({ default: m.DraftStudio })));
const Dialog = React.lazy(() => import('./pages/Dialog').then(m => ({ default: m.Dialog })));
const Discussion = React.lazy(() => import('./pages/Discussion').then(m => ({ default: m.Discussion })));
const ResearchWorkbench = React.lazy(() => import('./pages/ResearchWorkbench').then(m => ({ default: m.ResearchWorkbench })));
const WorkbenchDiscussion = React.lazy(() => import('./pages/WorkbenchDiscussion').then(m => ({ default: m.WorkbenchDiscussion })));
const WorkbenchWiki = React.lazy(() => import('./pages/WorkbenchObjectAdapters').then(m => ({ default: m.WorkbenchWiki })));
const WritingOverview = React.lazy(() => import('./pages/writing/WritingOverview').then(m => ({ default: m.WritingOverview })));
const OutlineManager = React.lazy(() => import('./pages/writing/OutlineManager').then(m => ({ default: m.OutlineManager })));
const SourcesCitations = React.lazy(() => import('./pages/writing/SourcesCitations').then(m => ({ default: m.SourcesCitations })));
const FiguresTables = React.lazy(() => import('./pages/writing/FiguresTables').then(m => ({ default: m.FiguresTables })));
const ReviewerSubmission = React.lazy(() => import('./pages/writing/ReviewerSubmission').then(m => ({ default: m.ReviewerSubmission })));
const EvolutionInbox = React.lazy(() => import('./pages/EvolutionInbox'));

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
              <ToastProvider>
              <Router>
                <MainLayout>
                  <Suspense fallback={<LazyFallback />}>
                    <Routes>
                      {/* Home */}
                      <Route path="/" element={<Workbench />} />

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
                      <Route path="/wiki" element={<WikiWorkbench />} />
                      <Route path="/projects" element={<Projects />} />
                      <Route path="/volume" element={<VolumeAnalysis />} />
                      <Route path="/inspiration" element={<Navigate to="/dialog?mode=inspiration" replace />} />
                      <Route path="/chat" element={<Navigate to="/dialog?mode=literature_qa" replace />} />
                      <Route path="/dialog" element={<Dialog />} />
                      <Route path="/discussion" element={<Discussion />} />
                      {/* ResearchWorkbench — gated by VITE_FLAG_RESEARCH_WORKBENCH; otherwise
                          the component itself redirects to /knowledge. */}
                      <Route path="/workbench/paper/:materialId" element={<ResearchWorkbench />} />
                      <Route path="/workbench/discussion" element={<WorkbenchDiscussion />} />
                      <Route path="/workbench/wiki" element={<WorkbenchWiki />} />
                      <Route path="/workbench/inspiration" element={<Navigate to="/dialog?mode=inspiration" replace />} />
                      <Route path="/jobs" element={<Jobs />} />
                      <Route path="/evolution" element={<EvolutionInbox />} />
                      <Route path="/settings" element={<SettingsPage />} />

                      {/* Fallback */}
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Suspense>
                </MainLayout>
                <CommandPalette />
                <McpPendingCallPoller />
              </Router>
            </ToastProvider>
            </DiscussionProvider>
          </PdfTabsProvider>
        </WritingProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
};

export default App;
