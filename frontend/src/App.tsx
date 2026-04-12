import { MainLayout } from './layouts/MainLayout';
import { DraftStudio } from './components/DraftStudio';
import { I18nProvider } from './contexts/I18nContext';
import { WritingProvider } from './contexts/WritingContext';

// Placeholder components for other routes
const Projects = () => (
  <div className="p-10">
    <div className="flex justify-between items-center mb-10">
      <div>
        <h1 className="font-headline text-4xl font-black tracking-tighter">项目管理</h1>
        <p className="text-muted-foreground mt-2">管理您的学术论文与研究项目</p>
      </div>
      <button className="bg-primary text-primary-foreground px-6 py-2.5 rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all">
        新建项目
      </button>
    </div>
    
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {[1, 2, 3].map(i => (
        <div key={i} className="glass-card p-6 rounded-2xl group hover:border-primary/50 transition-all cursor-pointer">
          <div className="flex justify-between items-start mb-4">
            <div className="h-10 w-10 bg-muted rounded-lg flex items-center justify-center text-primary group-hover:bg-primary/10 group-hover:scale-110 transition-all">
              <span className="font-black text-xl italic">P{i}</span>
            </div>
            <span className="bg-green-100 text-green-700 text-[10px] font-bold px-2 py-0.5 rounded-full uppercase">In Progress</span>
          </div>
          <h3 className="font-headline font-bold text-lg mb-2 group-hover:text-primary transition-colors">基于量子纠缠的分布式计算框架设计 v{i}.0</h3>
          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">本研究旨在探讨如何利用量子纠缠特性提升分布式节点的通信效率...</p>
          <div className="mt-6 flex items-center justify-between text-[10px] border-t pt-4 border-muted">
             <span className="text-muted-foreground font-medium uppercase tracking-wider">更新于: 2026-04-09</span>
             <span className="font-bold text-foreground tabular-nums">1.2k Words</span>
          </div>
        </div>
      ))}
    </div>
  </div>
);

const App = () => {
  return (
    <I18nProvider>
      <WritingProvider>
        <Router>
          <MainLayout>
            <Routes>
              <Route path="/projects" element={<Projects />} />
              <Route path="/draft" element={<DraftStudio />} />
              <Route path="/" element={<Navigate to="/projects" replace />} />
              {/* Missing routes fall back to projects */}
              <Route path="*" element={<Navigate to="/projects" replace />} />
            </Routes>
          </MainLayout>
        </Router>
      </WritingProvider>
    </I18nProvider>
  );
};

export default App;
