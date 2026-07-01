import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useLocation, NavLink } from 'react-router-dom';
import {
  BookOpen,
  BookMarked,
  BookOpenCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  Edit3,
  FileText,
  Folder,
  FolderKanban,
  HelpCircle,
  Image,
  LayoutDashboard,
  List,
  Menu,
  PencilLine,
  Settings,
  ShieldCheck,
  Activity,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';
import { useWriting } from '@/contexts/WritingContext';
import { useI18n } from '@/contexts/I18nContext';
import { getWritingBackendService } from '@/services/writingBackend';
import type { WritingProject } from '@/types/resources';
import { useToast } from '@/components/ui/Toast';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

const SCHOLAR_AI_DOCS_URL = 'https://github.com/xiaolongyao-lut/Scholar-AI';

/* ─── NavItem: Single sidebar link ─── */
function NavItem({
  to,
  icon,
  label,
  end,
  collapsed,
  activePaths,
  onNavigate,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  end?: boolean;
  collapsed?: boolean;
  activePaths?: string[];
  onNavigate?: () => void;
}) {
  const location = useLocation();
  // When `activePaths` is supplied, the item lights up on every path that
  // starts with any of those prefixes. Falls back to NavLink's default
  // isActive when no activePaths is given.
  const customActive = activePaths
    ? activePaths.some(prefix => prefix === '/'
        ? location.pathname === '/'
        : location.pathname === prefix || location.pathname.startsWith(prefix + '/'))
    : null;
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) => {
        const active = customActive ?? isActive;
        return cn(
          'relative group flex items-center gap-3 rounded-xl px-3 py-2.5 font-label text-sm transition-all duration-200',
          active
            ? 'translate-x-[2px] border border-white/10 bg-white/12 text-white shadow-[0_10px_24px_rgba(15,23,42,0.18)] font-medium'
            : 'border border-transparent text-white/58 hover:border-white/8 hover:bg-white/6 hover:text-white'
        );
      }}
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
function NavGroup({ icon, label, basePath, collapsed, children, onNavigate }: {
  icon: React.ReactNode;
  label: string;
  basePath: string;
  collapsed?: boolean;
  children: { to: string; icon: React.ReactNode; label: string; end?: boolean }[];
  onNavigate?: () => void;
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
            'flex w-full items-center justify-center rounded-xl border px-3 py-2.5 transition-all duration-200',
            isInGroup
              ? 'border-white/10 bg-white/12 text-white shadow-[0_10px_24px_rgba(15,23,42,0.18)]'
              : 'border-transparent text-white/58 hover:border-white/8 hover:bg-white/6 hover:text-white'
          )}
        >
          {icon}
        </button>
        <div className="absolute left-full top-0 z-50 ml-2 min-w-[180px] rounded-2xl border border-white/10 bg-sidebar/95 py-2 shadow-2xl opacity-0 transition-opacity pointer-events-none group-hover:pointer-events-auto group-hover:opacity-100 backdrop-blur-xl">
          <div className="px-3 py-1.5 text-[10px] font-label font-medium text-white/30 uppercase tracking-wider">{label}</div>
          {children.map(child => (
            <NavLink
              key={child.to}
              to={child.to}
              end={child.end}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 px-3 py-2 text-xs font-label transition-colors',
                  isActive ? 'bg-white/12 text-sidebar-accent' : 'text-white/60 hover:bg-white/6 hover:text-white'
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
          'flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 font-label text-sm transition-all duration-200',
          isInGroup
            ? 'border-white/10 bg-white/10 text-white shadow-[0_10px_24px_rgba(15,23,42,0.18)] font-medium'
            : 'border-transparent text-white/58 hover:border-white/8 hover:bg-white/6 hover:text-white'
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
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2.5 rounded-lg px-2.5 py-2 font-label text-xs transition-colors',
                      isActive
                        ? 'bg-white/12 text-sidebar-accent font-medium'
                        : 'text-white/50 hover:bg-white/6 hover:text-white'
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
  const closeButtonRef = React.useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    const handleEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' || event.key === 'Esc' || event.code === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
      }
    };
    const focusTimer = window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    document.addEventListener('keydown', handleEscape, true);
    document.addEventListener('keyup', handleEscape, true);
    window.addEventListener('keydown', handleEscape, true);
    window.addEventListener('keyup', handleEscape, true);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleEscape, true);
      document.removeEventListener('keyup', handleEscape, true);
      window.removeEventListener('keydown', handleEscape, true);
      window.removeEventListener('keyup', handleEscape, true);
    };
  }, [open, onClose]);

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
          role="dialog"
          aria-modal="true"
          aria-labelledby="help-dialog-title"
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
              <h2 id="help-dialog-title" className="font-headline text-lg text-foreground flex items-center gap-2.5">
                <HelpCircle size={20} className="text-primary" />
                <span>{t('nav.help_docs')}</span>
              </h2>
              <button
                ref={closeButtonRef}
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
                <a
                  href={SCHOLAR_AI_DOCS_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline font-label text-xs flex items-center gap-1.5"
                >
                  {t('nav.view_docs')}
                  <ChevronRight size={12} />
                </a>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ─── Config Popover ─── */
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- 写作 header config 弹层, 重构后暂未挂载, 保留供后续恢复
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
export const MainLayout = ({ children, className }: { children: React.ReactNode; className?: string }) => {
  const navigate = useNavigate();
  const { toast: _toast } = useToast();
  const { activeProjectId, setActiveProjectId, leftNavCollapsed, setLeftNavCollapsed, zenMode } = useWriting();
  const { t } = useI18n();
  const location = useLocation();
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [_isConfigOpen, _setIsConfigOpen] = useState(false);
  const [_isNotifOpen, _setIsNotifOpen] = useState(false);
  const [headerProjects, setHeaderProjects] = useState<Array<{ id: string; title: string }>>([]);
  const [_projectLoading, setProjectLoading] = useState(false);

  const isWritingRoute = location.pathname.startsWith('/writing');
  const isProjectsRoute = location.pathname.startsWith('/projects');
  const routeProjectId = useMemo(() => {
    const params = new URLSearchParams(location.search);
    return (params.get('project_id') ?? params.get('project') ?? '').trim();
  }, [location.search]);

  const _getHeaderTitle = () => {
    if (isWritingRoute) return t('writing.workbench_title');
    if (location.pathname.startsWith('/knowledge')) return t('kb.title');
    if (location.pathname.startsWith('/wiki')) return '知识沉淀';
    if (location.pathname.startsWith('/projects')) return t('projects.title');
    if (location.pathname.startsWith('/settings')) return t('settings.title');
    if (location.pathname.startsWith('/jobs')) return t('jobs.title');
    if (location.pathname.startsWith('/volume')) return t('volume.title');
    if (location.pathname.startsWith('/dialog')) return t('nav.workbench');
    if (location.pathname.startsWith('/discussion')) return t('nav.multi_agent_discussion');
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

      if (routeProjectId) {
        if (activeProjectId !== routeProjectId) {
          setActiveProjectId(routeProjectId);
        }
        return;
      }

      if (!activeProjectId || !normalized.some((project) => project.id === activeProjectId)) {
        if (isProjectsRoute) {
          if (activeProjectId) {
            setActiveProjectId('');
          }
          return;
        }
        setActiveProjectId(normalized[0].id);
      }
    } catch {
      setHeaderProjects([]);
    } finally {
      setProjectLoading(false);
    }
  }, [activeProjectId, isProjectsRoute, routeProjectId, setActiveProjectId]);

  useEffect(() => {
    void loadHeaderProjects();
  }, [loadHeaderProjects, location.pathname]);

  const _notificationItems = headerProjects.length === 0
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
    : routeProjectId && headerProjects.some(project => project.id === routeProjectId)
      ? routeProjectId
      : routeProjectId
        ? routeProjectId
      : (isProjectsRoute ? '' : (headerProjects[0]?.id ?? ''));

  const _handleProjectSelectorChange = useCallback((projectId: string) => {
    setActiveProjectId(projectId);
    if (isProjectsRoute) {
      navigate('/projects');
    }
  }, [isProjectsRoute, navigate, setActiveProjectId]);

  const _handleDeleteProject = useCallback(async () => {
    if (!selectedProjectId) return;
    const project = headerProjects.find(p => p.id === selectedProjectId);
    if (!project || !window.confirm(`确定要删除项目「${project.title}」吗？删除后无法恢复。`)) return;
    try {
      const svc = getWritingBackendService();
      await svc.deleteProject(selectedProjectId);
      await loadHeaderProjects();
    } catch { /* ignore */ }
  }, [selectedProjectId, headerProjects, loadHeaderProjects]);

  const closeMobileNav = useCallback(() => {
    setIsMobileNavOpen(false);
  }, []);

  const renderNavigation = useCallback((collapsed: boolean, onNavigate?: () => void) => (
    <>
      <NavItem
        to="/dialog"
        icon={<BookOpen size={20} />}
        label={t('nav.workbench')}
        collapsed={collapsed}
        activePaths={['/dialog', '/chat', '/intelligent-chat', '/inspiration']}
        onNavigate={onNavigate}
      />
      <NavItem
        to="/knowledge"
        icon={<Database size={20} />}
        label={t('nav.knowledge')}
        collapsed={collapsed}
        activePaths={['/knowledge']}
        onNavigate={onNavigate}
      />

      <NavGroup
        icon={<PencilLine size={20} />}
        label={t('nav.side_writing')}
        basePath="/writing"
        collapsed={collapsed}
        onNavigate={onNavigate}
        children={[
          { to: '/writing', icon: <LayoutDashboard size={16} />, label: t('nav.side_writing_overview'), end: true },
          { to: '/writing/draft', icon: <Edit3 size={16} />, label: t('nav.side_draft_studio') },
          { to: '/writing/outline', icon: <List size={16} />, label: t('nav.side_outline') },
          { to: '/writing/sources', icon: <BookMarked size={16} />, label: t('nav.side_sources') },
          { to: '/writing/figures', icon: <Image size={16} />, label: t('nav.side_figures') },
          { to: '/writing/reviewer', icon: <ShieldCheck size={16} />, label: t('nav.side_submission') },
        ]}
      />

      <NavItem
        to="/wiki"
        icon={<BookOpenCheck size={20} />}
        label="知识沉淀"
        collapsed={collapsed}
        activePaths={['/wiki']}
        onNavigate={onNavigate}
      />
      <NavItem to="/projects" icon={<FolderKanban size={20} />} label={t('nav.projects')} collapsed={collapsed} onNavigate={onNavigate} />
      <NavItem to="/volume" icon={<FileText size={20} />} label={t('nav.volume')} collapsed={collapsed} onNavigate={onNavigate} />
      <NavItem to="/jobs" icon={<Activity size={20} />} label={t('nav.jobs')} collapsed={collapsed} onNavigate={onNavigate} />
      <NavItem to="/settings" icon={<Settings size={20} />} label={t('nav.settings')} collapsed={collapsed} onNavigate={onNavigate} />
    </>
  ), [t]);

  return (
    <div className={`app-shell flex h-screen w-full overflow-hidden selection:bg-primary/20 ${className || ''}`}>
      <button
        type="button"
        onClick={() => setIsMobileNavOpen(true)}
        aria-label="打开导航"
        className="fixed right-3 top-3 z-40 inline-flex h-10 w-10 items-center justify-center rounded-md border border-outline-variant/60 bg-surface-lowest/95 text-foreground shadow-lg backdrop-blur transition-colors hover:border-primary/35 hover:text-primary md:hidden"
      >
        <Menu size={20} />
      </button>

      <AnimatePresence>
        {isMobileNavOpen ? (
          <motion.div
            className="fixed inset-0 z-50 md:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            <button
              type="button"
              aria-label="关闭导航"
              onClick={closeMobileNav}
              className="absolute inset-0 bg-black/45"
            />
            <motion.aside
              initial={{ x: -300 }}
              animate={{ x: 0 }}
              exit={{ x: -300 }}
              transition={{ duration: 0.18, ease: 'easeOut' }}
              className="glass-sidebar relative flex h-full w-[280px] max-w-[82vw] flex-col shadow-2xl"
            >
              <div className="sidebar-brand-shell flex items-center justify-between px-5 py-4">
                <div className="flex min-w-0 items-center gap-3">
                  <img
                    src="/app-icon-128.png"
                    alt=""
                    aria-hidden="true"
                    className="h-10 w-10 shrink-0 rounded-xl object-contain shadow-[0_8px_24px_rgba(0,0,0,0.24)]"
                  />
                  <div className="flex min-w-0 flex-col">
                    <div className="truncate font-display text-xl font-semibold text-white">Scholar AI</div>
                    <div className="mt-0.5 truncate font-label text-[10px] uppercase tracking-wider text-white/30">{t('nav.system_health')}</div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={closeMobileNav}
                  aria-label="关闭导航"
                  className="rounded-sm p-1.5 text-white/45 transition-colors hover:bg-white/10 hover:text-white"
                >
                  <X size={18} />
                </button>
              </div>
              <nav className="custom-scrollbar flex flex-1 flex-col gap-0.5 overflow-y-auto px-2">
                {renderNavigation(false, closeMobileNav)}
              </nav>
              <div className="sidebar-footer-shell p-3">
                <div className="flex items-center gap-2 px-2">
                  <ThemeToggle compact={false} />
                  <button
                    type="button"
                    onClick={() => {
                      closeMobileNav();
                      setIsHelpOpen(true);
                    }}
                    className="rounded-md p-2 text-white/40 transition-colors hover:bg-white/10 hover:text-white"
                    title={t('nav.help_docs')}
                    aria-label={t('nav.help_docs')}
                  >
                    <HelpCircle size={18} />
                  </button>
                </div>
              </div>
            </motion.aside>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* ── Sidebar ── */}
      <motion.aside
        initial={false}
        animate={{
          width: leftNavCollapsed ? 72 : 260,
          opacity: zenMode ? 0.1 : 1,
          pointerEvents: zenMode ? 'none' : 'auto'
        }}
        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
        className="glass-sidebar z-30 hidden h-full flex-shrink-0 flex-col md:flex"
      >
        {/* Brand */}
        <div className={cn('sidebar-brand-shell flex items-center overflow-hidden', leftNavCollapsed ? 'flex-col justify-center gap-2 px-3 py-4' : 'justify-between px-6 py-5')}>
          <AnimatePresence mode="wait">
            {!leftNavCollapsed && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="flex min-w-0 items-center gap-3"
              >
                <img
                  src="/app-icon-128.png"
                  alt=""
                  aria-hidden="true"
                  className="h-10 w-10 shrink-0 rounded-xl object-contain shadow-[0_8px_24px_rgba(0,0,0,0.24)]"
                />
                <div className="flex min-w-0 flex-col">
                  <h1 className="truncate font-display text-xl font-semibold text-white">Scholar AI</h1>
                  <p className="mt-0.5 truncate font-label text-[10px] uppercase tracking-wider text-white/30">{t('nav.system_health')}</p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          {leftNavCollapsed && (
            <img
              src="/app-icon-128.png"
              alt=""
              aria-hidden="true"
              className="h-10 w-10 shrink-0 rounded-xl object-contain shadow-[0_8px_24px_rgba(0,0,0,0.24)]"
            />
          )}
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
        <nav className="custom-scrollbar flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-1">
          {renderNavigation(leftNavCollapsed)}
        </nav>

        {/* Bottom actions */}
        <div className="sidebar-footer-shell mt-auto p-3">
          <div className={cn(
            "flex items-center gap-2",
            leftNavCollapsed ? "justify-center" : "justify-start px-2"
          )}>
            <ThemeToggle compact={leftNavCollapsed} />
            {!leftNavCollapsed && (
              <button
                type="button"
                onClick={() => setIsHelpOpen(true)}
                className="p-2 text-white/40 hover:text-white hover:bg-white/10 transition-colors rounded-md"
                title={t('nav.help_docs')}
                aria-label={t('nav.help_docs')}
              >
                <HelpCircle size={18} />
              </button>
            )}
          </div>
        </div>
      </motion.aside>

      {/* ── Main Content ── */}
      <div className="app-main-panel flex min-w-0 flex-1 flex-col">

        {/* Page Content */}
        <main
          data-testid="app-main"
          className="flex-1 overflow-auto custom-scrollbar relative"
        >
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
