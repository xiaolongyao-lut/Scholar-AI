import { ManuscriptSection, WritingMaterial } from '@/types/writing';

export const getSimulationSectionsForProject = (projectId: string): ManuscriptSection[] => {
  return [
    { id: 'sec-1', projectId, titleZh: '摘要', titleEn: 'Abstract', status: 'done', wordCount: 350, order: 1, notesZh: '核心贡献点需突出', notesEn: 'Highlight core contributions' },
    { id: 'sec-2', projectId, titleZh: '引言', titleEn: 'Introduction', status: 'drafting', wordCount: 1200, order: 2, notesZh: '需补充近期文献', notesEn: 'Need more recent citations' },
    { id: 'sec-3', projectId, titleZh: '相关工作', titleEn: 'Related Work', status: 'not_started', wordCount: 0, order: 3 },
    { id: 'sec-4', projectId, titleZh: '方法论', titleEn: 'Methodology', status: 'reviewing', wordCount: 2500, order: 4 },
  ];
};

export const getSimulationDraftForSection = (projectId: string, sectionId: string): string => {
  if (sectionId === 'sec-1') {
    return "本文提出了一种基于多代理协作的轻量级工作流编排引擎。在分布式环境下，传统的中控式调度方案面临单点故障和通信延迟。我们利用量子纠缠态的一致性协议，实现了零延迟的状态同步...";
  }
  return "Section content placeholder for " + sectionId;
};

export const getSimulationMaterialsForProject = (projectId: string): WritingMaterial[] => {
  return [
    { id: 'mat-1', titleZh: '量子纠缠协议 2024', titleEn: 'Quantum Entanglement Protocols 2024', summaryZh: '分析了当前量子同步的主要瓶颈...', summaryEn: 'Analyzes major bottlenecks in quantum sync...', type: 'PAPER', focusPointsZh: ['同步效率', '误码率'], focusPointsEn: ['Sync Efficiency', 'Bit Error Rate'] },
    { id: 'mat-2', titleZh: '分布式系统综述', titleEn: 'Distributed Systems Review', summaryZh: '2023年顶级期刊综述...', summaryEn: 'Top-tier journal review 2023...', type: 'BOOK', focusPointsZh: ['容错性'], focusPointsEn: ['Fault Tolerance'] },
  ];
};
