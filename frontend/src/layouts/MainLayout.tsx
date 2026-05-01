import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation, NavLink } from 'react-router-dom';
import { 
  BarChart3, 
  BookOpen, 
  BookMarked,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Edit3, 
  FileEdit,
  FileText,
  Folder,
  FolderPlus,
  FolderKanban, 
  HelpCircle,
  Image,
  Layers,
  LayoutDashboard,
  List,
  MessageCircle,
  PencilLine,
  Settings, 
  Bell,
  ShieldCheck,
  Activity,
  Lightbulb,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';
import { useWriting } from '@/contexts/WritingContext';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingProject } from '@/types/resources';
import { useToast } from '@/components/ui/Toast';

/* ─── NavItem: Single sidebar link ─── */
function NavItem({ to, icon, label, end, collapsed }: { to: string; icon: React.ReactNode; label: string; end?: boolean; collapsed?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 px-3 py-2.5 font-label text-sm transition-colors relative group',
          isActive
            ? 'text-white bg-white/10 border-l-[3px] border-sidebar-accent font-medium'
            : 'text-white/55 hover:text-white hover:bg-white/5 border-l-[3px] border-transparent'
        )
      }
    >
      {icon}
      {!collapsed && <span className="truncate">{label}</span>}
      {collapsed && (
        <div className="absolute left-full ml-3 px-2.5 py-1.5 bg-foreground text-background text-xs font-label rounded shadow-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50 whitespace-nowrap">
          {label}
        </div>
      )}
    </NavLink>
  );
}

/* ─── NavGroup: Collapsible group with children ─── */
function NavGroup({ icon, label, basePath, collapsed, children }: {
  icon: React.ReactNode;
  label: string;
  basePath: string;
  collapsed?: boolean;
  children: { to: string; icon: React.ReactNode; label: string; end?: boolean }[];
}) {
  const location = useLocation();
  const isInGroup = location.pathname.startsWith(basePath);
  const [isOpen, setIsOpen] = useState(isInGroup);

  useEffect(() => {
    if (isInGroup && !isOpen) setIsOpen(true);
  }, [isInGroup]);

  if (collapsed) {
    return (
      <div className="relative group">
        <button
          type="button"
          aria-label={label}
          title={label}
          className={cn(
            'w-full flex items-center justify-center px-3 py-2.5 transition-colors border-l-[3px]',
            isInGroup
              ? 'text-white bg-white/10 border-sidebar-accent'
              : 'text-white/55 hover:text-white hover:bg-white/5 border-transparent'
          )}
        >
          {icon}
        </button>
        <div className="absolute left-full top-0 ml-2 bg-sidebar border border-sidebar-border rounded-lg shadow-xl py-2 min-w-[180px] opacity-0 group-hover:opacity-100 pointer-events-none group-hover:pointer-events-auto transition-opacity z-50">
          <div className="px-3 py-1.5 text-[10px] font-label font-medium text-white/30 uppercase tracking-wider">{label}</div>
          {children.map(child => (
            <NavLink
              key={child.to}
              to={child.to}
              end={child.end}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 px-3 py-2 text-xs font-label transition-colors',
                  isActive ? 'text-sidebar-accent bg-white/10' : 'text-white/60 hover:text-white hover:bg-white/5'
                )
              }
            >
              {child.icon}
              {child.label}
            </NavLink>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'w-full flex items-center gap-3 px-3 py-2.5 font-label text-sm transition-colors border-l-[3px]',
          isInGroup
            ? 'text-white bg-white/8 border-sidebar-accent font-medium'
            : 'text-white/55 hover:text-white hover:bg-white/5 border-transparent'
        )}
      >
        {icon}
        <span className="flex-1 text-left truncate">{label}</span>
        <motion.span animate={{ rotate: isOpen ? 180 : 0 }} transition={{ duration: 0.15 }}>
          <ChevronDown size={14} className="text-white/25" />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="overflow-hidden"
          >
            <div className="ml-4 pl-4 border-l border-white/10 space-y-0.5 py-1">
              {children.map(child => (
                <NavLink
                  key={child.to}
                  to={child.to}
                  end={child.end}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2.5 px-2 py-2 font-label text-xs transition-colors rounded-sm',
                      isActive
                        ? 'text-sidebar-accent bg-white/10 font-medium'
                        : 'text-white/50 hover:text-white hover:bg-white/5'
                    )
                  }
                >
                  {child.icon}
                  {child.label}
                </NavLink>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ─── Help Dialog ─── */
function HelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="bg-surface-lowest w-[400px] rounded-lg shadow-xl border border-outline-variant flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-outline-variant">
              <h2 className="font-headline text-lg text-foreground flex items-center gap-2.5">
                <HelpCircle size={20} className="text-primary" />
                <span>{t('nav.help_docs')}</span>
              </h2>
              <button
                type="button"
                onClick={onClose}
                title={t('common.close')}
                aria-label={t('common.close')}
                className="text-foreground/40 hover:text-foreground transition-colors p-1 rounded-sm hover:bg-surface-high"
              >
                <ChevronRight size={18} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="font-body text-sm text-foreground/80 leading-relaxed">
                {t('nav.help_welcome')}
              </p>
              <ul className="space-y-2.5 font-label text-xs text-foreground/70">
                <li className="flex items-center gap-2.5"><BookOpen size={14} className="text-primary/60" /> <span>{t('nav.help_workbench')}</span></li>
                <li className="flex items-center gap-2.5"><PencilLine size={14} className="text-primary/60" /> <span>{t('nav.help_writing')}</span></li>
                <li className="flex items-center gap-2.5"><Database size={14} className="text-primary/60" /> <span>{t('nav.help_kb')}</span></li>
                <li className="flex items-center gap-2.5"><Folder size={14} className="text-primary/60" /> <span>{t('nav.help_projects')}</span></li>
              </ul>
              <div className="pt-4 mt-4 border-t border-outline-variant">
                <button className="text-primary hover:underline font-label text-xs flex items-center gap-1.5">
                  {t('nav.view_docs')}
                  <ChevronRight size={12} />
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ─── Config Popover ─── */
function ConfigPopover({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const { scope, setScope, outputMode, setOutputMode } = useWriting();

  return (
    <AnimatePresence>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={onClose} />
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute top-12 left-0 z-50 w-[380px] p-4 bg-surface-lowest border border-outline-variant shadow-2xl rounded-xl flex flex-col gap-4"
          >
            <h3 className="font-display text-sm font-semibold text-foreground border-b border-outline-variant pb-2">
              {t('writing.processing_scope')} & {t('writing.mode')}
            </h3>

            {/* Scopes */}
            <div className="space-y-2">
              <p className="font-label text-[10px] text-foreground/40 uppercase tracking-widest font-medium">{t('writing.processing_scope')}</p>
              <div className="flex flex-wrap gap-2">
                {(['selection', 'section', 'full_draft'] as const).map(s => (
                  <button
                    type="button"
                    key={s}
                    onClick={() => setScope(s)}
                    className={cn(
                      'px-2.5 py-1 text-[10px] font-medium rounded border transition-all',
                      scope === s
                        ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                        : 'bg-surface-high border-outline-variant/30 text-foreground/40 hover:text-foreground'
                    )}
                  >
                    {t(`writing.scope_${s === 'full_draft' ? 'full' : s}`)}
                  </button>
                ))}
              </div>
            </div>

            {/* Output mode */}
            <div className="space-y-2">
              <p className="font-label text-[10px] text-foreground/40 uppercase tracking-widest font-medium">{t('writing.export_mode')}</p>
              <div className="flex gap-1.5 p-1 bg-surface-high rounded-lg border border-outline-variant/30">
                {(['latex', 'markdown', 'plain'] as const).map(mode => (
                  <button
                    type="button"
                    key={mode}
                    onClick={() => setOutputMode(mode)}
                    className={cn(
                      'flex-1 py-1.5 text-[10px] font-medium uppercase tracking-wider rounded transition-all',
                      outputMode === mode
                        ? 'bg-primary text-primary-foreground shadow-sm'
                        : 'text-foreground/40 hover:text-foreground'
                    )}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ─── MainLayout ─── */
export const MainLayout = ({ children }: { children: React.ReactNode }) => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const { activeProjectId, setActiveProjectId, leftNavCollapsed, setLeftNavCollapsed, zenMode } = useWriting();
  const { t } = useI18n();
  const location = useLocation();
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isConfigOpen, setIsConfigOpen] = useState(false);
  const [isNotifOpen, setIsNotifOpen] = useState(false);
  const [headerProjects, setHeaderProjects] = useState<Array<{ id: string; title: string }>>([]);
  const [projectLoading, setProjectLoading] = useState(false);

  const isWritingRoute = location.pathname.startsWith('/writing');

  const getHeaderTitle = () => {
    if (isWritingRoute) return t('writing.workbench_title');
    if (location.pathname.startsWith('/knowledge')) return t('kb.title');
    if (location.pathname.startsWith('/projects')) return t('projects.title');
    if (location.pathname.startsWith('/settings')) return t('settings.title');
    if (location.pathname.startsWith('/jobs')) return t('jobs.title');
    if (location.pathname.startsWith('/volume')) return t('volume.title');
    if (location.pathname.startsWith('/inspiration')) return t('nav.inspiration');
    if (location.pathname.startsWith('/chat')) return 'Intelligent Chat';
    return t('workbench.title');
  };

  const loadHeaderProjects = useCallback(async () => {
    setProjectLoading(true);
    try {
      const svc = getWritingBackendService();
      const list = await svc.listProjects();
      const sorted = [...list].sort((a: WritingProject, b: WritingProject) => {
        const ta = Date.parse(a.created_at || '') || 0;
        const tb = Date.parse(b.created_at || '') || 0;
        return tb - ta;
      });

      const seenTitles = new Set<string>();
      const normalized = sorted
        .filter((project: WritingProject) => {
          const key = (project.title || '').trim().toLowerCase();
          if (!key) return true;
          if (seenTitles.has(key)) return false;
          seenTitles.add(key);
          return true;
        })
        .map((project: WritingProject) => ({
          id: project.project_id,
          title: project.title,
        }));
      setHeaderProjects(normalized);

      if (normalized.length === 0) {
        if (activeProjectId) {
          setActiveProjectId('');
        }
        return;
      }

      if (!activeProjectId || !normalized.some((project) => project.id === activeProjectId)) {
        setActiveProjectId(normalized[0].id);
      }
    } catch {
      setHeaderProjects([]);
    } finally {
      setProjectLoading(false);
    }
  }, [activeProjectId, setActiveProjectId]);

  useEffect(() => {
    void loadHeaderProjects();
  }, [loadHeaderProjects, location.pathname]);

  const notificationItems = headerProjects.length === 0
    ? [{
      id: 'notif-no-project',
      title: t('nav.notifications_empty'),
      message: t('nav.notifications_no_project'),
      time: '刚刚',
    }]
    : [{
      id: 'notif-project-loaded',
      title: t('nav.notifications_title'),
      message: t('nav.notifications_projects_loaded', { count: headerProjects.length }),
      time: '刚刚',
    }];

  const selectedProjectId = activeProjectId && headerProjects.some(project => project.id === activeProjectId)
    ? activeProjectId
    : (headerProjects[0]?.id ?? '');

  const handleDeleteProject = useCallback(async () => {
    if (!selectedProjectId) return;
    const project = headerProjects.find(p => p.id === selectedProjectId);
    if (!project || !window.confirm(`确定要删除项目「${project.title}」吗？删除后无法恢复。`)) return;
    try {
      const svc = getWritingBackendService();
      await svc.deleteProject(selectedProjectId);
      await loadHeaderProjects();
    } catch { /* ignore */ }
  }, [selectedProjectId, headerProjects, loadHeaderProjects]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-surface selection:bg-primary/20">
      {/* ── Sidebar ── */}
      <motion.aside
        initial={false}
        animate={{
          width: leftNavCollapsed ? 72 : 260,
          opacity: zenMode ? 0.1 : 1,
          pointerEvents: zenMode ? 'none' : 'auto'
        }}
        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
        className="glass-sidebar flex flex-col h-full z-30 flex-shrink-0"
      >
        {/* Brand */}
        <div className={cn('flex items-center overflow-hidden', leftNavCollapsed ? 'px-3 py-5 justify-center' : 'px-6 py-5 justify-between')}>
          <AnimatePresence mode="wait">
            {!leftNavCollapsed && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="flex flex-col"
              >
                <h1 className="font-display text-xl font-semibold text-white">Scholar AI</h1>
                <p className="font-label text-[10px] tracking-wider text-white/30 uppercase mt-0.5">{t('nav.system_health')}</p>
              </motion.div>
            )}
          </AnimatePresence>
          <button
            type="button"
            onClick={() => setLeftNavCollapsed(!leftNavCollapsed)}
            aria-label={leftNavCollapsed ? t('nav.expand_sidebar') : t('nav.collapse_sidebar')}
            className="p-1.5 rounded-sm hover:bg-white/10 text-white/40 transition-colors flex-shrink-0"
          >
            {leftNavCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 flex flex-col gap-0.5 overflow-y-auto custom-scrollbar">
          <NavItem to="/" icon={<BookOpen size={20} />} label={t('nav.workbench')} end collapsed={leftNavCollapsed} />

          <NavGroup
            icon={<PencilLine size={20} />}
            label={t('nav.side_writing')}
            basePath="/writing"
            collapsed={leftNavCollapsed}
            children={[
              { to: '/writing', icon: <LayoutDashboard size={16} />, label: t('nav.side_writing_overview'), end: true },
              { to: '/writing/draft', icon: <Edit3 size={16} />, label: t('nav.side_draft_studio') },
              { to: '/writing/outline', icon: <List size={16} />, label: t('nav.side_outline') },
              { to: '/writing/sources', icon: <BookMarked size={16} />, label: t('nav.side_sources') },
              { to: '/writing/figures', icon: <Image size={16} />, label: t('nav.side_figures') },
              { to: '/writing/reviewer', icon: <ShieldCheck size={16} />, label: t('nav.side_submission') },
            ]}
          />

          <NavItem to="/knowledge" icon={<Database size={20} />} label={t('nav.knowledge')} collapsed={leftNavCollapsed} />
          <NavItem to="/projects" icon={<FolderKanban size={20} />} label={t('nav.projects')} collapsed={leftNavCollapsed} />
          <NavItem to="/chat" icon={<MessageCircle size={20} />} label="Chat" collapsed={leftNavCollapsed} />
          <NavItem to="/inspiration" icon={<Lightbulb size={20} />} label={t('nav.inspiration')} collapsed={leftNavCollapsed} />
          <NavItem to="/volume" icon={<FileText size={20} />} label={t('nav.volume')} collapsed={leftNavCollapsed} />
          <NavItem to="/jobs" icon={<Activity size={20} />} label={t('nav.jobs')} collapsed={leftNavCollapsed} />
          <NavItem to="/settings" icon={<Settings size={20} />} label={t('nav.settings')} collapsed={leftNavCollapsed} />
        </nav>

        {/* Bottom spacer */}
        <div className="p-4 mt-auto" />
      </motion.aside>

      {/* ── Main Content ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header Bar */}
        <motion.header
          animate={{
            opacity: zenMode ? 0.1 : 1,
            pointerEvents: zenMode ? 'none' : 'auto'
          }}
          className="h-14 flex-shrink-0 flex items-center justify-between px-8 bg-surface-lowest border-b border-outline-variant z-20"
        >
          <div className="flex items-center gap-6 relative">
            <h2 className="font-display text-lg font-semibold text-foreground">
              {getHeaderTitle()}
            </h2>
            <div className="h-5 w-px bg-outline-variant" />

            {/* Config trigger (writing routes only) */}
            {isWritingRoute && (
              <button
                type="button"
                onClick={() => setIsConfigOpen(!isConfigOpen)}
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-xs font-label font-medium',
                  isConfigOpen
                    ? 'bg-primary/10 border-primary text-primary'
                    : 'bg-surface-high border-outline-variant text-foreground/50 hover:bg-surface-highest'
                )}
              >
                <Settings size={14} className={cn('transition-transform', isConfigOpen && 'rotate-90')} />
                {t('common.config')}
              </button>
            )}
            <ConfigPopover open={isConfigOpen} onClose={() => setIsConfigOpen(false)} />

            {/* Project selector */}
            <div className="flex items-center gap-2 px-3 py-1.5 bg-surface-high rounded-full border border-outline-variant/40 shadow-sm">
              <Folder size={14} className="text-primary/60" />
              {projectLoading ? (
                <span className="text-[11px] font-label font-medium text-foreground/40">项目加载中...</span>
              ) : headerProjects.length > 0 ? (
                <select
                  value={selectedProjectId}
                  onChange={(e) => setActiveProjectId(e.target.value)}
                  title="当前项目"
                  aria-label="当前项目"
                  className="bg-transparent text-[11px] font-label font-medium text-foreground focus:outline-none cursor-pointer"
                >
                  {headerProjects.map(project => (
                    <option key={project.id} value={project.id}>{project.title}</option>
                  ))}
                </select>
              ) : (
                <span className="text-[11px] font-label font-medium text-foreground/50">{t('nav.no_project')}</span>
              )}
              <button
                type="button"
                onClick={() => navigate('/projects')}
                aria-label={t('projects.new_project')}
                className="p-1 rounded-md text-foreground/40 hover:text-primary hover:bg-surface-highest transition-colors"
                title={t('projects.new_project')}
              >
                <FolderPlus size={13} />
              </button>
              {headerProjects.length > 0 && (
                <button
                  type="button"
                  onClick={handleDeleteProject}
                  aria-label="删除当前项目"
                  className="p-1 rounded-md text-foreground/40 hover:text-red-500 hover:bg-red-50 transition-colors"
                  title="删除当前项目"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 relative">
            <kbd className="hidden lg:flex items-center gap-1 px-2 py-1 bg-surface-high/60 rounded text-[10px] font-label text-foreground/30 border border-outline-variant/50 cursor-pointer hover:bg-surface-high transition-colors"
              onClick={() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}
            >
              <span>⌘K</span>
            </kbd>
            <button
              type="button"
              onClick={() => {
                setIsNotifOpen((prev) => {
                  const next = !prev;
                  if (next && headerProjects.length === 0) {
                    toast(t('nav.notifications_no_project'), 'info');
                  }
                  return next;
                });
              }}
              className="relative p-2 text-foreground/40 hover:text-foreground transition-colors rounded-sm hover:bg-surface-high"
              title={t('nav.notifications')}
              aria-label={t('nav.notifications')}
            >
              <Bell size={18} />
              {!activeProjectId && <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-primary rounded-full" />}
            </button>
            <button
              type="button"
              onClick={() => setIsHelpOpen(true)}
              className="p-2 text-foreground/40 hover:text-foreground transition-colors rounded-sm hover:bg-surface-high"
              title={t('nav.help_docs')}
              aria-label={t('nav.help_docs')}
            >
              <HelpCircle size={18} />
            </button>

            <AnimatePresence>
              {isNotifOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setIsNotifOpen(false)} />
                  <motion.div
                    initial={{ opacity: 0, y: 8, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 8, scale: 0.96 }}
                    transition={{ duration: 0.15 }}
                    className="absolute top-11 right-0 z-50 w-[320px] bg-surface-lowest border border-outline-variant rounded-xl shadow-2xl overflow-hidden"
                  >
                    <div className="px-4 py-3 border-b border-outline-variant flex items-center justify-between">
                      <h4 className="font-headline text-sm font-semibold text-foreground">{t('nav.notifications_title')}</h4>
                      <button
                        type="button"
                        onClick={() => setIsNotifOpen(false)}
                        title={t('common.close')}
                        aria-label={t('common.close')}
                        className="p-1 text-foreground/30 hover:text-foreground transition-colors"
                      >
                        <ChevronRight size={14} />
                      </button>
                    </div>
                    <div className="p-3 space-y-2">
                      {notificationItems.map(item => (
                        <div key={item.id} className="rounded-lg border border-outline-variant/40 bg-surface-high px-3 py-2.5">
                          <p className="font-label text-xs font-medium text-foreground">{item.title}</p>
                          <p className="font-body text-[11px] text-foreground/55 mt-1 leading-relaxed break-words">{item.message}</p>
                          <p className="font-label text-[10px] text-foreground/35 mt-1.5">{item.time}</p>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        </motion.header>

        {/* Page Content */}
        <main className="flex-1 overflow-auto custom-scrollbar relative">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              transition={{ duration: 0.2 }}
              className="h-full"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* Help Dialog */}
      <HelpDialog open={isHelpOpen} onClose={() => setIsHelpOpen(false)} />
    </div>
  );
};
