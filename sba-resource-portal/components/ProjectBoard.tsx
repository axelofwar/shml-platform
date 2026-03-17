import React, { useState, useEffect } from 'react';

interface Task {
  id: string;
  title: string;
  description: string;
  status: 'backlog' | 'in-progress' | 'review' | 'done';
  priority: 'p0' | 'p1' | 'p2';
  category: string;
  expert: string;
  effort: string;
  agentIntegration?: string;
  createdAt?: number;
  updatedAt?: number;
}

const defaultTasks: Task[] = [
  // P0 - Critical
  {
    id: 'storage-1',
    title: 'Persistent File Storage',
    description: 'IndexedDB-based storage so users don\'t need to re-upload files within a session.',
    status: 'backlog',
    priority: 'p0',
    category: 'Storage',
    expert: 'Enterprise Architect',
    effort: '4h',
    agentIntegration: 'None - Client-side only'
  },
  {
    id: 'storage-2',
    title: 'Folder Upload Support',
    description: 'Allow users to drag-and-drop or select entire folders.',
    status: 'backlog',
    priority: 'p0',
    category: 'Storage',
    expert: 'UX Engineer',
    effort: '3h',
    agentIntegration: 'None - Client-side only'
  },
  {
    id: 'context-1',
    title: 'Deal Context Switching',
    description: 'Multi-deal management with named workspaces.',
    status: 'backlog',
    priority: 'p0',
    category: 'M&A Workflow',
    expert: 'M&A Advisor',
    effort: '6h',
    agentIntegration: 'AgentPlaybook for semantic context storage'
  },
  {
    id: 'sba-1',
    title: 'SBA 7(a) Eligibility Checker',
    description: 'Interactive checklist for deal eligibility validation.',
    status: 'backlog',
    priority: 'p0',
    category: 'M&A Workflow',
    expert: 'SBA Lender',
    effort: '8h',
    agentIntegration: 'SBASkill (new)'
  },
  // P1 - High Priority
  {
    id: 'reference-1',
    title: 'Document Reference Overlay',
    description: 'Click citations to see source document sections.',
    status: 'backlog',
    priority: 'p1',
    category: 'Document Intelligence',
    expert: 'UX Engineer',
    effort: '6h',
    agentIntegration: 'Embedding Service'
  },
  {
    id: 'calc-1',
    title: 'DSCR Calculator Widget',
    description: 'Interactive Debt Service Coverage Ratio calculator.',
    status: 'backlog',
    priority: 'p1',
    category: 'M&A Calculators',
    expert: 'CPA/Underwriter',
    effort: '4h',
    agentIntegration: 'None - Client-side'
  },
  {
    id: 'export-1',
    title: 'Call Notes Export',
    description: 'Export Q&A session for CRM paste.',
    status: 'backlog',
    priority: 'p1',
    category: 'Call Center',
    expert: 'Operations Manager',
    effort: '2h',
    agentIntegration: 'None - Client-side'
  },
  // P2 - Nice to Have
  {
    id: 'agent-1',
    title: 'Agent-Assisted DD Checklist',
    description: 'AI generates due diligence checklist.',
    status: 'backlog',
    priority: 'p2',
    category: 'M&A Workflow',
    expert: 'M&A Attorney',
    effort: '8h',
    agentIntegration: 'ACE Agent with DueDiligenceSkill'
  },
  {
    id: 'agent-2',
    title: 'Red Flag Detection',
    description: 'Scan financials for M&A risks.',
    status: 'backlog',
    priority: 'p2',
    category: 'Document Intelligence',
    expert: 'CPA',
    effort: '10h',
    agentIntegration: 'ACE Agent with FinancialAnalysisSkill'
  },
];

const STORAGE_KEY = 'sba-portal-project-board';

const priorityColors = {
  'p0': 'bg-red-900/50 border-red-700 text-red-300',
  'p1': 'bg-yellow-900/50 border-yellow-700 text-yellow-300',
  'p2': 'bg-blue-900/50 border-blue-700 text-blue-300',
};

const priorityLabels = {
  'p0': '🔴 P0 Critical',
  'p1': '🟡 P1 High',
  'p2': '🔵 P2 Nice to Have',
};

const statusColumns = [
  { id: 'backlog', title: '📋 Backlog', color: 'bg-slate-800' },
  { id: 'in-progress', title: '🔨 In Progress', color: 'bg-blue-900/30' },
  { id: 'review', title: '👀 Review', color: 'bg-yellow-900/30' },
  { id: 'done', title: '✅ Done', color: 'bg-green-900/30' },
];

const defaultCategories = [
  'Storage', 'M&A Workflow', 'Document Intelligence', 'M&A Calculators',
  'Call Center', 'Agent Integration', 'Accessibility', 'Compliance'
];

interface ProjectBoardProps {
  isOpen: boolean;
  onClose: () => void;
}

interface TaskFormData {
  title: string;
  description: string;
  status: Task['status'];
  priority: Task['priority'];
  category: string;
  expert: string;
  effort: string;
  agentIntegration: string;
}

const emptyFormData: TaskFormData = {
  title: '',
  description: '',
  status: 'backlog',
  priority: 'p1',
  category: '',
  expert: '',
  effort: '',
  agentIntegration: '',
};

const ProjectBoard: React.FC<ProjectBoardProps> = ({ isOpen, onClose }) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filter, setFilter] = useState<string>('all');
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [formData, setFormData] = useState<TaskFormData>(emptyFormData);
  const [customCategory, setCustomCategory] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Load tasks from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        setTasks(parsed);
      } catch (e) {
        console.error('Failed to parse stored tasks:', e);
        setTasks(defaultTasks);
      }
    } else {
      setTasks(defaultTasks);
    }
  }, []);

  // Save tasks to localStorage whenever they change
  useEffect(() => {
    if (tasks.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
    }
  }, [tasks]);

  if (!isOpen) return null;

  const filteredTasks = filter === 'all'
    ? tasks
    : tasks.filter(t => t.priority === filter || t.category === filter);

  const categories = [...new Set([...defaultCategories, ...tasks.map(t => t.category)])];

  const moveTask = (taskId: string, newStatus: Task['status']) => {
    setTasks(prev => prev.map(t =>
      t.id === taskId ? { ...t, status: newStatus, updatedAt: Date.now() } : t
    ));
    if (selectedTask?.id === taskId) {
      setSelectedTask(prev => prev ? { ...prev, status: newStatus } : null);
    }
  };

  const handleCreateTask = () => {
    setFormData(emptyFormData);
    setCustomCategory('');
    setIsCreating(true);
    setIsEditing(false);
    setSelectedTask(null);
  };

  const handleEditTask = (task: Task) => {
    setFormData({
      title: task.title,
      description: task.description,
      status: task.status,
      priority: task.priority,
      category: task.category,
      expert: task.expert,
      effort: task.effort,
      agentIntegration: task.agentIntegration || '',
    });
    setCustomCategory('');
    setIsEditing(true);
    setIsCreating(false);
  };

  const handleSaveTask = () => {
    const category = customCategory || formData.category;
    if (!formData.title.trim() || !category) {
      alert('Title and Category are required');
      return;
    }

    if (isCreating) {
      const newTask: Task = {
        id: `task-${Date.now()}`,
        ...formData,
        category,
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      setTasks(prev => [...prev, newTask]);
    } else if (isEditing && selectedTask) {
      setTasks(prev => prev.map(t =>
        t.id === selectedTask.id
          ? { ...t, ...formData, category, updatedAt: Date.now() }
          : t
      ));
      setSelectedTask(prev => prev ? { ...prev, ...formData, category } : null);
    }

    setIsCreating(false);
    setIsEditing(false);
    setFormData(emptyFormData);
    setCustomCategory('');
  };

  const handleDeleteTask = () => {
    if (selectedTask) {
      setTasks(prev => prev.filter(t => t.id !== selectedTask.id));
      setSelectedTask(null);
      setShowDeleteConfirm(false);
    }
  };

  const handleResetToDefaults = () => {
    if (window.confirm('Reset all tasks to defaults? This will delete any custom tasks.')) {
      setTasks(defaultTasks);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(defaultTasks));
    }
  };

  const handleExportTasks = () => {
    const dataStr = JSON.stringify(tasks, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sba-portal-tasks-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImportTasks = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const imported = JSON.parse(event.target?.result as string);
        if (Array.isArray(imported)) {
          setTasks(imported);
          alert(`Imported ${imported.length} tasks`);
        }
      } catch (err) {
        alert('Failed to import: Invalid JSON file');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  // Task Form Modal
  const renderTaskForm = () => {
    if (!isCreating && !isEditing) return null;

    return (
      <div className="absolute inset-0 bg-black/70 flex items-center justify-center p-4 z-10">
        <div className="bg-slate-800 rounded-xl border border-slate-600 w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-slate-100">
              {isCreating ? '➕ Create New Task' : '✏️ Edit Task'}
            </h3>
            <button
              onClick={() => { setIsCreating(false); setIsEditing(false); }}
              className="p-1 rounded hover:bg-slate-700 text-slate-400"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="space-y-4">
            {/* Title */}
            <div>
              <label className="block text-xs text-slate-400 uppercase mb-1">Title *</label>
              <input
                type="text"
                value={formData.title}
                onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                placeholder="Task title..."
              />
            </div>

            {/* Description */}
            <div>
              <label className="block text-xs text-slate-400 uppercase mb-1">Description</label>
              <textarea
                value={formData.description}
                onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500 h-20 resize-none"
                placeholder="Task description..."
              />
            </div>

            {/* Priority & Status Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 uppercase mb-1">Priority</label>
                <select
                  value={formData.priority}
                  onChange={(e) => setFormData(prev => ({ ...prev, priority: e.target.value as Task['priority'] }))}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                >
                  <option value="p0">🔴 P0 - Critical</option>
                  <option value="p1">🟡 P1 - High</option>
                  <option value="p2">🔵 P2 - Nice to Have</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 uppercase mb-1">Status</label>
                <select
                  value={formData.status}
                  onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value as Task['status'] }))}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                >
                  {statusColumns.map(col => (
                    <option key={col.id} value={col.id}>{col.title}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Category */}
            <div>
              <label className="block text-xs text-slate-400 uppercase mb-1">Category *</label>
              <select
                value={formData.category}
                onChange={(e) => {
                  if (e.target.value === '__custom__') {
                    setFormData(prev => ({ ...prev, category: '' }));
                  } else {
                    setFormData(prev => ({ ...prev, category: e.target.value }));
                    setCustomCategory('');
                  }
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
              >
                <option value="">Select category...</option>
                {categories.map(cat => (
                  <option key={cat} value={cat}>{cat}</option>
                ))}
                <option value="__custom__">+ Add Custom Category</option>
              </select>
              {(formData.category === '' || customCategory) && (
                <input
                  type="text"
                  value={customCategory}
                  onChange={(e) => setCustomCategory(e.target.value)}
                  className="w-full mt-2 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                  placeholder="Enter custom category..."
                />
              )}
            </div>

            {/* Expert & Effort Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 uppercase mb-1">Expert/Owner</label>
                <input
                  type="text"
                  value={formData.expert}
                  onChange={(e) => setFormData(prev => ({ ...prev, expert: e.target.value }))}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                  placeholder="e.g., UX Engineer"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 uppercase mb-1">Effort Estimate</label>
                <input
                  type="text"
                  value={formData.effort}
                  onChange={(e) => setFormData(prev => ({ ...prev, effort: e.target.value }))}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                  placeholder="e.g., 4h, 2d"
                />
              </div>
            </div>

            {/* Agent Integration */}
            <div>
              <label className="block text-xs text-slate-400 uppercase mb-1">Agent Integration</label>
              <input
                type="text"
                value={formData.agentIntegration}
                onChange={(e) => setFormData(prev => ({ ...prev, agentIntegration: e.target.value }))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-slate-500"
                placeholder="e.g., ACE Agent, Embedding Service, None"
              />
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleSaveTask}
                className="flex-1 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium transition-colors"
              >
                {isCreating ? 'Create Task' : 'Save Changes'}
              </button>
              <button
                onClick={() => { setIsCreating(false); setIsEditing(false); }}
                className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg font-medium transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  // Task Detail Modal
  const renderTaskDetail = () => {
    if (!selectedTask || isEditing || isCreating) return null;

    return (
      <div className="absolute inset-0 bg-black/60 flex items-center justify-center p-4 z-10">
        <div className="bg-slate-800 rounded-xl border border-slate-600 w-full max-w-lg p-6">
          <div className="flex items-start justify-between mb-4">
            <div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${priorityColors[selectedTask.priority]}`}>
                {priorityLabels[selectedTask.priority]}
              </span>
              <h3 className="text-lg font-bold text-slate-100 mt-2">{selectedTask.title}</h3>
            </div>
            <button
              onClick={() => setSelectedTask(null)}
              className="p-1 rounded hover:bg-slate-700 text-slate-400"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <p className="text-slate-300 text-sm mb-4">{selectedTask.description}</p>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <span className="text-xs text-slate-500 uppercase">Category</span>
              <p className="text-sm text-slate-300">{selectedTask.category}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500 uppercase">Expert</span>
              <p className="text-sm text-slate-300">{selectedTask.expert || '-'}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500 uppercase">Effort</span>
              <p className="text-sm text-slate-300">{selectedTask.effort || '-'}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500 uppercase">Status</span>
              <p className="text-sm text-slate-300 capitalize">{selectedTask.status.replace('-', ' ')}</p>
            </div>
          </div>

          {selectedTask.agentIntegration && (
            <div className="mb-4 p-3 rounded-lg bg-purple-900/20 border border-purple-700/50">
              <span className="text-xs text-purple-400 uppercase font-medium">🤖 Agent Integration</span>
              <p className="text-sm text-purple-200 mt-1">{selectedTask.agentIntegration}</p>
            </div>
          )}

          {/* Move to status */}
          <div className="mb-4">
            <span className="text-xs text-slate-500 uppercase block mb-2">Move to:</span>
            <div className="flex gap-2 flex-wrap">
              {statusColumns.map(col => (
                <button
                  key={col.id}
                  onClick={() => moveTask(selectedTask.id, col.id as Task['status'])}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    selectedTask.status === col.id
                      ? 'bg-slate-600 text-white'
                      : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                  }`}
                >
                  {col.title.split(' ')[0]} {col.title.split(' ').slice(1).join(' ')}
                </button>
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 pt-2 border-t border-slate-700">
            <button
              onClick={() => handleEditTask(selectedTask)}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              Edit
            </button>
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-red-600/20 hover:bg-red-600/40 text-red-400 border border-red-700/50 rounded-lg font-medium transition-colors"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Delete
            </button>
          </div>

          {/* Delete Confirmation */}
          {showDeleteConfirm && (
            <div className="mt-4 p-3 bg-red-900/30 border border-red-700 rounded-lg">
              <p className="text-sm text-red-300 mb-2">Are you sure you want to delete this task?</p>
              <div className="flex gap-2">
                <button
                  onClick={handleDeleteTask}
                  className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white rounded text-sm font-medium"
                >
                  Yes, Delete
                </button>
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-sm font-medium"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 rounded-xl border border-slate-700 w-full max-w-7xl max-h-[90vh] overflow-hidden flex flex-col relative">

        {/* Task Form Modal */}
        {renderTaskForm()}

        {/* Task Detail Modal */}
        {renderTaskDetail()}

        {/* Header */}
        <div className="p-4 border-b border-slate-700 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-50">🎯 M&A Call Center Portal - Project Board</h2>
            <p className="text-sm text-slate-400 mt-1">
              Expert recommendations for B2B M&A advisory + Agent integrations
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Add Task Button */}
            <button
              onClick={handleCreateTask}
              className="flex items-center gap-2 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium transition-colors"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Task
            </button>

            {/* More Actions Dropdown */}
            <div className="relative group">
              <button className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                </svg>
              </button>
              <div className="absolute right-0 top-full mt-1 w-48 bg-slate-800 border border-slate-700 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-20">
                <button
                  onClick={handleExportTasks}
                  className="w-full px-4 py-2 text-left text-sm text-slate-300 hover:bg-slate-700 rounded-t-lg flex items-center gap-2"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Export Tasks
                </button>
                <label className="w-full px-4 py-2 text-left text-sm text-slate-300 hover:bg-slate-700 flex items-center gap-2 cursor-pointer">
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  Import Tasks
                  <input type="file" accept=".json" onChange={handleImportTasks} className="hidden" />
                </label>
                <button
                  onClick={handleResetToDefaults}
                  className="w-full px-4 py-2 text-left text-sm text-red-400 hover:bg-slate-700 rounded-b-lg flex items-center gap-2"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Reset to Defaults
                </button>
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="p-4 border-b border-slate-800 flex items-center gap-2 flex-wrap">
          <span className="text-sm text-slate-400">Filter:</span>
          <button
            onClick={() => setFilter('all')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === 'all' ? 'bg-slate-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            All ({tasks.length})
          </button>
          <button
            onClick={() => setFilter('p0')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === 'p0' ? 'bg-red-600 text-white' : 'bg-red-900/30 text-red-400 hover:bg-red-900/50'
            }`}
          >
            🔴 P0 ({tasks.filter(t => t.priority === 'p0').length})
          </button>
          <button
            onClick={() => setFilter('p1')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === 'p1' ? 'bg-yellow-600 text-white' : 'bg-yellow-900/30 text-yellow-400 hover:bg-yellow-900/50'
            }`}
          >
            🟡 P1 ({tasks.filter(t => t.priority === 'p1').length})
          </button>
          <button
            onClick={() => setFilter('p2')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === 'p2' ? 'bg-blue-600 text-white' : 'bg-blue-900/30 text-blue-400 hover:bg-blue-900/50'
            }`}
          >
            🔵 P2 ({tasks.filter(t => t.priority === 'p2').length})
          </button>
          <div className="h-4 w-px bg-slate-700 mx-2" />
          {categories.slice(0, 6).map(cat => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                filter === cat ? 'bg-slate-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Kanban Board */}
        <div className="flex-1 overflow-x-auto p-4">
          <div className="flex gap-4 min-w-max h-full">
            {statusColumns.map(column => (
              <div
                key={column.id}
                className={`w-80 ${column.color} rounded-lg border border-slate-700 flex flex-col`}
              >
                <div className="p-3 border-b border-slate-700">
                  <h3 className="font-semibold text-slate-200 flex items-center justify-between">
                    {column.title}
                    <span className="text-xs bg-slate-700 px-2 py-0.5 rounded-full">
                      {filteredTasks.filter(t => t.status === column.id).length}
                    </span>
                  </h3>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-2 max-h-[50vh]">
                  {filteredTasks
                    .filter(t => t.status === column.id)
                    .map(task => (
                      <div
                        key={task.id}
                        onClick={() => { setSelectedTask(task); setShowDeleteConfirm(false); }}
                        className={`p-3 rounded-lg border cursor-pointer hover:brightness-110 transition-all ${priorityColors[task.priority]}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h4 className="font-medium text-sm text-slate-100">{task.title}</h4>
                          {task.effort && (
                            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-800/50 text-slate-300 shrink-0">
                              {task.effort}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-400 mt-1 line-clamp-2">{task.description}</p>
                        <div className="flex items-center gap-2 mt-2 flex-wrap">
                          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800/50 text-slate-300">
                            {task.category}
                          </span>
                          {task.agentIntegration && !task.agentIntegration.toLowerCase().startsWith('none') && (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-purple-900/50 text-purple-300 border border-purple-700/50">
                              🤖
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  {filteredTasks.filter(t => t.status === column.id).length === 0 && (
                    <div className="text-center py-8 text-slate-500 text-sm">
                      No tasks
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Summary Stats */}
        <div className="p-4 border-t border-slate-700 bg-slate-800/50">
          <div className="flex items-center justify-between text-sm">
            <div className="flex gap-6">
              <span className="text-slate-400">
                <span className="text-red-400 font-bold">{tasks.filter(t => t.priority === 'p0').length}</span> P0
              </span>
              <span className="text-slate-400">
                <span className="text-yellow-400 font-bold">{tasks.filter(t => t.priority === 'p1').length}</span> P1
              </span>
              <span className="text-slate-400">
                <span className="text-blue-400 font-bold">{tasks.filter(t => t.priority === 'p2').length}</span> P2
              </span>
              <span className="text-slate-400">
                <span className="text-green-400 font-bold">{tasks.filter(t => t.status === 'done').length}</span> Done
              </span>
            </div>
            <div className="flex gap-6">
              <span className="text-slate-400">
                <span className="text-purple-400 font-bold">
                  {tasks.filter(t => t.agentIntegration && !t.agentIntegration.toLowerCase().startsWith('none')).length}
                </span> Agent Integrations
              </span>
              <span className="text-slate-400">
                Total: <span className="text-emerald-400 font-bold">{tasks.length}</span> tasks
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProjectBoard;
