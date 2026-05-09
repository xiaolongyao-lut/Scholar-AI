import React, { useState, useEffect } from 'react';
import { Send, RotateCw, Copy, Plus, MessageSquare } from 'lucide-react';
import { discussionApi, DiscussionMessage, DiscussionStatusResponse } from '../../services/discussionApi';

interface DiscussionPanelProps {
  onInsertToEditor?: (content: string) => void;
}

const ROLE_LABELS: Record<string, string> = {
  proponent: '支持方',
  opponent: '反对方',
  reviewer: '审稿人',
  moderator: '主持人',
};
const ROLE_COLORS: Record<string, string> = {
  proponent: 'bg-green-100 text-green-800 border-green-300',
  opponent: 'bg-red-100 text-red-800 border-red-300',
  reviewer: 'bg-blue-100 text-blue-800 border-blue-300',
  moderator: 'bg-purple-100 text-purple-800 border-purple-300',
};

export const DiscussionPanel: React.FC<DiscussionPanelProps> = ({ onInsertToEditor }) => {
  const [topic, setTopic] = useState('');
  const [selectedRoles, setSelectedRoles] = useState<string[]>(['proponent', 'opponent']);
  const [maxTurns, setMaxTurns] = useState(5);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DiscussionMessage[]>([]);
  const [status, setStatus] = useState<DiscussionStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);

  const roleOptions = [
    { label: '支持方', value: 'proponent' },
    { label: '反对方', value: 'opponent' },
    { label: '审稿人', value: 'reviewer' },
    { label: '主持人', value: 'moderator' },
  ];

  const handleCreateDiscussion = async () => {
    if (!topic.trim()) {
      alert('请输入讨论主题');
      return;
    }
    if (selectedRoles.length < 2) {
      alert('至少选择 2 个角色');
      return;
    }

    setLoading(true);
    try {
      const response = await discussionApi.createDiscussion({
        topic: topic.trim(),
        roles: selectedRoles,
        max_turns: maxTurns,
      });
      setSessionId(response.session_id);
      setMessages([]);
      await fetchStatus(response.session_id);
    } catch (error) {
      alert('创建讨论失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const fetchStatus = async (sid: string) => {
    try {
      const statusData = await discussionApi.getStatus(sid);
      setStatus(statusData);
    } catch (error) {
      console.error('获取状态失败', error);
    }
  };

  const fetchHistory = async (sid: string) => {
    try {
      const historyData = await discussionApi.getHistory(sid);
      setMessages(historyData.messages);
    } catch (error) {
      console.error('获取历史失败', error);
    }
  };

  const handleRunTurn = async () => {
    if (!sessionId) return;

    setRunning(true);
    try {
      await discussionApi.runTurn(sessionId);
      await fetchHistory(sessionId);
      await fetchStatus(sessionId);
    } catch (error) {
      alert('运行讨论失败');
      console.error(error);
    } finally {
      setRunning(false);
    }
  };

  const handleCopySynthesis = () => {
    if (status?.synthesis) {
      navigator.clipboard.writeText(status.synthesis);
      alert('已复制综合结论');
    }
  };

  const handleInsertSynthesis = () => {
    if (status?.synthesis && onInsertToEditor) {
      onInsertToEditor(status.synthesis);
      alert('已插入编辑器');
    }
  };

  const toggleRole = (role: string) => {
    if (selectedRoles.includes(role)) {
      setSelectedRoles(selectedRoles.filter(r => r !== role));
    } else {
      setSelectedRoles([...selectedRoles, role]);
    }
  };

  useEffect(() => {
    if (sessionId) {
      fetchHistory(sessionId);
    }
  }, [sessionId]);

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
        <MessageSquare className="w-6 h-6" />
        多 Agent 讨论
      </h2>

      {!sessionId ? (
        <div className="bg-white rounded-lg shadow p-6 space-y-6">
          <div>
            <label className="block text-sm font-medium mb-2">讨论主题</label>
            <textarea
              rows={3}
              placeholder="例如：因果推断在自然语言处理中的应用前景"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">参与角色（至少选择 2 个）</label>
            <div className="flex flex-wrap gap-2">
              {roleOptions.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => toggleRole(opt.value)}
                  className={`px-4 py-2 rounded-md border transition-colors ${
                    selectedRoles.includes(opt.value)
                      ? 'bg-blue-500 text-white border-blue-600'
                      : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">最大轮次</label>
            <input
              type="number"
              min={1}
              max={20}
              value={maxTurns}
              onChange={(e) => setMaxTurns(Number(e.target.value))}
              className="w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <button
            onClick={handleCreateDiscussion}
            disabled={loading}
            className="w-full bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            <Send className="w-4 h-4" />
            {loading ? '创建中...' : '创建讨论'}
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">{status?.topic || ''}</h3>
                <p className="text-sm text-gray-500">
                  轮次：{status?.current_turn || 0} / {maxTurns} | 状态：
                  <span className={`ml-1 ${status?.status === 'active' ? 'text-green-600' : 'text-gray-600'}`}>
                    {status?.status === 'active' ? '进行中' : status?.status === 'completed' ? '已完成' : '已综合'}
                  </span>
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleRunTurn}
                  disabled={running || status?.status !== 'active'}
                  className="bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2"
                >
                  <RotateCw className={`w-4 h-4 ${running ? 'animate-spin' : ''}`} />
                  {running ? '运行中...' : '运行下一轮'}
                </button>
                <button
                  onClick={() => setSessionId(null)}
                  className="bg-gray-200 text-gray-700 px-4 py-2 rounded-md hover:bg-gray-300 flex items-center gap-2"
                >
                  <Plus className="w-4 h-4" />
                  新建讨论
                </button>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-4">讨论历史</h3>
            <div className="space-y-4 max-h-[500px] overflow-y-auto">
              {messages.length === 0 ? (
                <p className="text-gray-500 text-center py-8">暂无发言</p>
              ) : (
                messages.map((msg) => (
                  <div key={msg.id} className="border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`px-3 py-1 rounded-full text-sm font-medium border ${ROLE_COLORS[msg.role] || 'bg-gray-100 text-gray-800 border-gray-300'}`}>
                        {ROLE_LABELS[msg.role] || msg.role}
                      </span>
                      <span className="text-xs text-gray-500">
                        {new Date(msg.timestamp).toLocaleString('zh-CN')}
                      </span>
                    </div>
                    <p className="whitespace-pre-wrap text-gray-700">{msg.content}</p>
                  </div>
                ))
              )}
            </div>
          </div>

          {status?.synthesis && (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">综合结论</h3>
                <div className="flex gap-2">
                  <button
                    onClick={handleCopySynthesis}
                    className="bg-gray-200 text-gray-700 px-3 py-1 rounded-md hover:bg-gray-300 flex items-center gap-1 text-sm"
                  >
                    <Copy className="w-4 h-4" />
                    复制
                  </button>
                  {onInsertToEditor && (
                    <button
                      onClick={handleInsertSynthesis}
                      className="bg-blue-500 text-white px-3 py-1 rounded-md hover:bg-blue-600 text-sm"
                    >
                      插入编辑器
                    </button>
                  )}
                </div>
              </div>
              <p className="whitespace-pre-wrap text-gray-700">{status.synthesis}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
