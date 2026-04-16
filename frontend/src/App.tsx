import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { DraftStudio } from './components/DraftStudio';
import { WritingProvider } from './contexts/WritingContext';
import { ToastProvider } from './components/ui/Toast';
import { CommandPalette } from './components/ui/CommandPalette';

// Pages
import { Workbench } from './pages/Workbench';
import { Projects } from './pages/Projects';
import { KnowledgeBase } from './pages/KnowledgeBase';
import { SettingsPage } from './pages/Settings';
import { VolumeAnalysis } from './pages/VolumeAnalysis';
import { Jobs } from './pages/Jobs';
import { Inspiration } from './pages/Inspiration';
import { WritingOverview } from './pages/writing/WritingOverview';
import { OutlineManager } from './pages/writing/OutlineManager';
import { SourcesCitations } from './pages/writing/SourcesCitations';
import { FiguresTables } from './pages/writing/FiguresTables';
import { ReviewerSubmission } from './pages/writing/ReviewerSubmission';

const App = () => {
  return (
    <WritingProvider>
        <ToastProvider>
          <Router>
            <MainLayout>
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
                <Route path="/projects" element={<Projects />} />
                <Route path="/volume" element={<VolumeAnalysis />} />
                <Route path="/inspiration" element={<Inspiration />} />
                <Route path="/jobs" element={<Jobs />} />
                <Route path="/settings" element={<SettingsPage />} />

                {/* Fallback */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </MainLayout>
            <CommandPalette />
          </Router>
        </ToastProvider>
      </WritingProvider>
  );
};

export default App;
