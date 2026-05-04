import React, { Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { WritingProvider } from './contexts/WritingContext';
import { ToastProvider } from './components/ui/Toast';
import { CommandPalette } from './components/ui/CommandPalette';

// Route-level lazy imports for code splitting (TASK-181)
const Workbench = React.lazy(() => import('./pages/Workbench').then(m => ({ default: m.Workbench })));
const Projects = React.lazy(() => import('./pages/Projects').then(m => ({ default: m.Projects })));
const KnowledgeBase = React.lazy(() => import('./pages/KnowledgeBase').then(m => ({ default: m.KnowledgeBase })));
const WikiWorkbench = React.lazy(() => import('./pages/WikiWorkbench').then(m => ({ default: m.WikiWorkbench })));
const SettingsPage = React.lazy(() => import('./pages/Settings').then(m => ({ default: m.SettingsPage })));
const VolumeAnalysis = React.lazy(() => import('./pages/VolumeAnalysis').then(m => ({ default: m.VolumeAnalysis })));
const Jobs = React.lazy(() => import('./pages/Jobs').then(m => ({ default: m.Jobs })));
const Inspiration = React.lazy(() => import('./pages/Inspiration').then(m => ({ default: m.Inspiration })));
const DraftStudio = React.lazy(() => import('./components/DraftStudio').then(m => ({ default: m.DraftStudio })));
const IntelligentChat = React.lazy(() => import('./pages/IntelligentChat').then(m => ({ default: m.IntelligentChat })));
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
    <WritingProvider>
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
                  <Route path="/wiki" element={<WikiWorkbench />} />
                  <Route path="/projects" element={<Projects />} />
                  <Route path="/volume" element={<VolumeAnalysis />} />
                  <Route path="/inspiration" element={<Inspiration />} />
                  <Route path="/chat" element={<IntelligentChat />} />
                  <Route path="/jobs" element={<Jobs />} />
                  <Route path="/settings" element={<SettingsPage />} />

                  {/* Fallback */}
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </MainLayout>
            <CommandPalette />
          </Router>
        </ToastProvider>
      </WritingProvider>
  );
};

export default App;
