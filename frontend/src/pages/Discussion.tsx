import React, { useState, useCallback } from 'react';
import { DiscussionPanel } from '@/components/DiscussionPanel';
import { useToast } from '@/components/ui/Toast';

export const Discussion: React.FC = () => {
  const { toast } = useToast();
  const [editorContent, setEditorContent] = useState<string>('');

  const handleInsertToEditor = useCallback((content: string) => {
    setEditorContent(prev => prev + '\n\n' + content);
    toast('已插入讨论结论', 'success');
  }, [toast]);

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="flex-none border-b border-border bg-card px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">多 Agent 讨论</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              让多个 AI agent 围绕同一话题进行结构化讨论，产出高质量的综述和批判性分析
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden p-6">
        <div className="h-full grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-full overflow-auto">
            <DiscussionPanel onInsertToEditor={handleInsertToEditor} />
          </div>

          <div className="h-full flex flex-col bg-card rounded-lg border border-border">
            <div className="flex-none px-4 py-3 border-b border-border">
              <h2 className="text-sm font-medium text-foreground">讨论结论预览</h2>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {editorContent ? (
                <div className="prose prose-sm max-w-none">
                  <pre className="whitespace-pre-wrap text-sm text-foreground/80">
                    {editorContent}
                  </pre>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground">
                  <p className="text-sm">讨论结论将显示在这里</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Discussion;
