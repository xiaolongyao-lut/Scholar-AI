import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { 
  BarChart3, 
  BookOpen, 
  ChevronLeft, 
  ChevronRight, 
  FileEdit, 
  FolderKanban, 
  Layers, 
  LogOut, 
  Moon, 
  Settings, 
  Sun, 
  UserCircle 
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';

interface SidebarItemProps {
  icon: React.ElementType;
  label: string;
  path: string;
  active?: boolean;
  collapsed?: boolean;
}

const SidebarItem = ({ icon: Icon, label, path, active, collapsed }: SidebarItemProps) => {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(path)}
      className={cn(
        "flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all group relative",
        active 
          ? "bg-primary text-primary-foreground shadow-lg shadow-primary/25" 
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon size={20} className={cn("transition-transform group-hover:scale-110", active && "scale-110")} />
      {!collapsed && (
        <span className="font-label text-sm font-medium whitespace-nowrap overflow-hidden">
          {label}
        </span>
      )}
      {collapsed && (
        <div className="absolute left-full ml-4 px-2 py-1 bg-foreground text-background text-xs rounded opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50 whitespace-nowrap">
          {label}
        </div>
      )}
    </button>
  );
};

export const MainLayout = ({ children }: { children: React.ReactNode }) => {
  const [collapsed, setCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const location = useLocation();

  const menuItems = [
    { icon: FolderKanban, label: "项目总览", path: "/projects" },
    { icon: FileEdit, label: "文稿创作", path: "/draft" },
    { icon: BookOpen, label: "资料库", path: "/knowledge" },
    { icon: BarChart3, label: "性能分析", path: "/analytics" },
    { icon: Layers, label: "技能市场", path: "/skills" },
  ];

  return (
    <div className={cn("flex h-screen w-full transition-colors duration-300", darkMode && "dark")}>
      {/* Sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 80 : 260 }}
        className="glass-sidebar flex flex-col h-full z-30 transition-shadow hover:shadow-2xl"
      >
        <div className="p-6 flex items-center justify-between overflow-hidden">
          <AnimatePresence mode="wait">
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="flex items-center gap-3"
              >
                <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-primary-foreground font-black italic">
                  MP
                </div>
                <span className="font-headline font-bold text-lg tracking-tight">Modular</span>
              </motion.div>
            )}
          </AnimatePresence>
          <button 
            onClick={() => setCollapsed(!collapsed)}
            className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground"
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        <nav className="flex-1 px-4 py-4 flex flex-col gap-2 overflow-y-auto custom-scrollbar">
          {menuItems.map((item) => (
            <SidebarItem 
              key={item.path}
              {...item}
              active={location.pathname === item.path}
              collapsed={collapsed}
            />
          ))}
        </nav>

        <div className="p-4 border-t border-sidebar-border flex flex-col gap-2">
          <button 
            onClick={() => setDarkMode(!darkMode)}
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-muted-foreground hover:bg-muted transition-all"
          >
            {darkMode ? <Sun size={20} /> : <Moon size={20} />}
            {!collapsed && <span className="text-sm font-medium">{darkMode ? "浅色模式" : "深色模式"}</span>}
          </button>
          
          <div className="flex items-center gap-3 px-3 py-4 mt-2">
            <UserCircle size={24} className="text-primary" />
            {!collapsed && (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold truncate">Xiao Long</p>
                <p className="text-[10px] text-muted-foreground truncate">Premium Agent</p>
              </div>
            )}
          </div>
        </div>
      </motion.aside>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden flex flex-col bg-background">
        <header className="h-16 px-8 flex items-center justify-between border-b border-border bg-white/50 backdrop-blur-sm z-20">
          <div className="flex items-center gap-4">
            <h2 className="font-headline font-semibold text-sm text-muted-foreground uppercase tracking-widest">
              {menuItems.find(i => i.path === location.pathname)?.label || "Dashboard"}
            </h2>
          </div>
          <div className="flex items-center gap-3">
             <div className="bg-secondary/10 text-secondary px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-tighter">
                Active Session: v40.2
             </div>
             <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center text-muted-foreground">
                <Settings size={16} />
             </div>
          </div>
        </header>
        
        <div className="flex-1 overflow-auto custom-scrollbar relative">
          {children}
        </div>
      </main>
    </div>
  );
};
