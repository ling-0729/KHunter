/**
 * 执行方案管理模块
 * 实现执行方案的创建、编辑、保存、导入、导出和执行功能
 */

const ExecutionPlanModule = {
    // 当前方案
    currentPlan: null,
    
    // 策略组合列表
    combinations: [],
    
    // 初始化模块
    init: function() {
        this.setupEventListeners();
        this.loadPlanList();
        this.loadSelectionStrategies();
    },
    
    // 设置事件监听器
    setupEventListeners: function() {
        const self = this;
        
        // 新建方案按钮
        document.getElementById('create-plan-btn').addEventListener('click', () => {
            self.createNewPlan();
        });
        
        // 添加策略组合按钮
        document.getElementById('add-combo-btn').addEventListener('click', () => {
            self.openAddComboModal();
        });
        
        // 保存方案按钮
        document.getElementById('save-plan-btn').addEventListener('click', () => {
            self.savePlan();
        });
        
        // 导出方案按钮
        document.getElementById('export-plan-btn').addEventListener('click', () => {
            self.exportPlan();
        });
        
        // 删除方案按钮
        document.getElementById('delete-plan-btn').addEventListener('click', () => {
            self.deletePlan();
        });
        
        // 执行方案按钮
        document.getElementById('run-plan-btn').addEventListener('click', () => {
            self.runPlan();
        });
        
        // 确认添加策略组合
        document.getElementById('confirm-add-combo-btn').addEventListener('click', () => {
            self.addStrategyCombo();
        });
        
        // 确认导入方案
        document.getElementById('confirm-import-btn').addEventListener('click', () => {
            self.importPlan();
        });
        
        // 方案名称输入变化时隐藏保存状态
        document.getElementById('plan-name-input').addEventListener('input', () => {
            document.getElementById('save-indicator').classList.remove('show');
        });
        
        // 方案描述输入变化时隐藏保存状态
        document.getElementById('plan-desc-input').addEventListener('input', () => {
            document.getElementById('save-indicator').classList.remove('show');
        });
    },
    
    // 加载方案列表
    loadPlanList: async function() {
        try {
            const response = await fetch('/api/execution/plans');
            const result = await response.json();
            
            if (result.success && result.data) {
                this.renderPlanList(result.data);
            } else {
                document.getElementById('plan-list').innerHTML = 
                    '<div class="text-center text-muted p-3">加载方案列表失败</div>';
            }
        } catch (error) {
            console.error('加载方案列表失败:', error);
            document.getElementById('plan-list').innerHTML = 
                '<div class="text-center text-muted p-3">加载方案列表失败</div>';
        }
    },
    
    // 渲染方案列表
    renderPlanList: function(plans) {
        const container = document.getElementById('plan-list');
        
        if (plans.length === 0) {
            container.innerHTML = '<div class="text-center text-muted p-3">暂无方案</div>';
            return;
        }
        
        container.innerHTML = plans.map(plan => `
            <div class="list-group-item plan-list-item p-3" data-plan-id="${plan.id}">
                <div class="font-weight-bold">${plan.name}</div>
                <div class="text-sm text-muted">${plan.description || '无描述'}</div>
                <div class="text-xs text-muted mt-1">${plan.combinations.length} 个策略组合</div>
            </div>
        `).join('');
        
        // 添加点击事件
        container.querySelectorAll('.plan-list-item').forEach(item => {
            item.addEventListener('click', () => {
                container.querySelectorAll('.plan-list-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                this.loadPlan(item.dataset.planId);
            });
        });
    },
    
    // 加载选股策略列表
    loadSelectionStrategies: async function() {
        try {
            const response = await fetch('/api/strategies');
            const result = await response.json();
            
            if (result.success && result.strategies) {
                const select = document.getElementById('selection-strategy');
                select.innerHTML = result.strategies.map(strategy => `
                    <option value="${strategy.name}">${strategy.display_name || strategy.name}</option>
                `).join('');
            }
        } catch (error) {
            console.error('加载选股策略失败:', error);
        }
    },
    
    // 创建新方案
    createNewPlan: function() {
        this.currentPlan = null;
        this.combinations = [];
        
        document.getElementById('plan-name-input').value = '';
        document.getElementById('plan-desc-input').value = '';
        document.getElementById('plan-title').textContent = '新建方案';
        document.getElementById('plan-description').textContent = '';
        document.getElementById('save-indicator').classList.remove('show');
        
        // 隐藏导出和删除按钮
        document.getElementById('export-plan-btn').style.display = 'none';
        document.getElementById('delete-plan-btn').style.display = 'none';
        
        this.renderCombinations();
    },
    
    // 加载方案详情
    loadPlan: async function(planId) {
        try {
            const response = await fetch(`/api/execution/plans/${planId}`);
            const result = await response.json();
            
            if (result.success && result.data) {
                this.currentPlan = result.data;
                this.combinations = result.data.combinations || [];
                
                document.getElementById('plan-name-input').value = result.data.name;
                document.getElementById('plan-desc-input').value = result.data.description || '';
                document.getElementById('plan-title').textContent = result.data.name;
                document.getElementById('plan-description').textContent = result.data.description || '';
                document.getElementById('save-indicator').classList.remove('show');
                
                // 显示导出和删除按钮
                document.getElementById('export-plan-btn').style.display = 'inline-block';
                document.getElementById('delete-plan-btn').style.display = 'inline-block';
                
                this.renderCombinations();
            } else {
                alert('加载方案失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('加载方案失败:', error);
            alert('加载方案失败');
        }
    },
    
    // 渲染策略组合列表
    renderCombinations: function() {
        const container = document.getElementById('strategy-combos-container');
        
        if (this.combinations.length === 0) {
            container.innerHTML = '<div class="text-center text-muted py-4">暂无策略组合</div>';
            return;
        }
        
        container.innerHTML = this.combinations.map((combo, index) => `
            <div class="strategy-combo-item" data-combo-id="${combo.id}">
                <div class="combo-header">
                    <span class="font-weight-bold">策略组合 ${index + 1}</span>
                    <div class="btn-group btn-group-sm">
                        <button class="btn btn-outline-secondary move-up-btn" ${index === 0 ? 'disabled' : ''}
                                title="上移" data-index="${index}">↑</button>
                        <button class="btn btn-outline-secondary move-down-btn" ${index === this.combinations.length - 1 ? 'disabled' : ''}
                                title="下移" data-index="${index}">↓</button>
                        <button class="btn btn-outline-warning edit-combo-btn" 
                                title="编辑" data-index="${index}">✏️</button>
                        <button class="btn btn-outline-danger remove-combo-btn" 
                                title="删除" data-index="${index}">🗑️</button>
                    </div>
                </div>
                <div class="combo-body">
                    <div class="combo-field">
                        <label>选股策略:</label>
                        <span>${combo.selection_strategy}</span>
                    </div>
                    <div class="combo-field">
                        <label>择时策略:</label>
                        <span>${this.getTimingLabel(combo.timing_strategy)}</span>
                    </div>
                    <div class="combo-field">
                        <label>状态:</label>
                        <span>${combo.enabled ? '✓ 启用' : '✗ 禁用'}</span>
                    </div>
                </div>
            </div>
        `).join('');
        
        // 添加事件监听器
        this.setupComboEventListeners();
    },
    
    // 获取择时策略显示名称
    getTimingLabel: function(timingStrategy) {
        const mapping = {
            'turtle': '海龟策略',
            'rsi': 'RSI策略',
            'bollinger': '布林带策略',
            'support': '支撑位策略'
        };
        return mapping[timingStrategy] || timingStrategy;
    },
    
    // 设置策略组合事件监听器
    setupComboEventListeners: function() {
        const self = this;
        
        // 上移
        document.querySelectorAll('.move-up-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                self.moveCombo(index, index - 1);
            });
        });
        
        // 下移
        document.querySelectorAll('.move-down-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                self.moveCombo(index, index + 1);
            });
        });
        
        // 编辑
        document.querySelectorAll('.edit-combo-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                self.editCombo(index);
            });
        });
        
        // 删除
        document.querySelectorAll('.remove-combo-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const index = parseInt(this.dataset.index);
                self.removeCombo(index);
            });
        });
    },
    
    // 移动策略组合位置
    moveCombo: function(fromIndex, toIndex) {
        if (toIndex < 0 || toIndex >= this.combinations.length) return;
        
        const combo = this.combinations.splice(fromIndex, 1)[0];
        this.combinations.splice(toIndex, 0, combo);
        
        document.getElementById('save-indicator').classList.remove('show');
        this.renderCombinations();
    },
    
    // 编辑策略组合
    editCombo: function(index) {
        const combo = this.combinations[index];
        
        document.getElementById('selection-strategy').value = combo.selection_strategy;
        document.getElementById('timing-strategy').value = combo.timing_strategy;
        document.getElementById('combo-enabled').checked = combo.enabled;
        
        // 保存当前编辑的索引
        this.editingComboIndex = index;
        
        // 显示弹窗
        const modal = new bootstrap.Modal(document.getElementById('add-combo-modal'));
        modal.show();
        
        // 修改按钮文字
        document.getElementById('add-combo-label').textContent = '编辑策略组合';
        document.getElementById('confirm-add-combo-btn').textContent = '确认修改';
    },
    
    // 删除策略组合
    removeCombo: function(index) {
        if (confirm('确定要删除这个策略组合吗？')) {
            this.combinations.splice(index, 1);
            document.getElementById('save-indicator').classList.remove('show');
            this.renderCombinations();
        }
    },
    
    // 打开添加策略组合弹窗
    openAddComboModal: function() {
        // 重置表单
        document.getElementById('selection-strategy').selectedIndex = 0;
        document.getElementById('timing-strategy').selectedIndex = 0;
        document.getElementById('combo-enabled').checked = true;
        
        // 清除编辑状态
        this.editingComboIndex = null;
        
        // 设置按钮文字
        document.getElementById('add-combo-label').textContent = '添加策略组合';
        document.getElementById('confirm-add-combo-btn').textContent = '确认添加';
        
        // 显示弹窗
        const modal = new bootstrap.Modal(document.getElementById('add-combo-modal'));
        modal.show();
    },
    
    // 添加策略组合
    addStrategyCombo: function() {
        const selectionStrategy = document.getElementById('selection-strategy').value;
        const timingStrategy = document.getElementById('timing-strategy').value;
        const enabled = document.getElementById('combo-enabled').checked;
        
        if (!selectionStrategy) {
            alert('请选择选股策略');
            return;
        }
        
        const combo = {
            id: this.editingComboIndex !== null ? 
                this.combinations[this.editingComboIndex].id : this.generateId(),
            selection_strategy: selectionStrategy,
            timing_strategy: timingStrategy,
            enabled: enabled
        };
        
        if (this.editingComboIndex !== null) {
            // 编辑模式
            this.combinations[this.editingComboIndex] = combo;
            this.editingComboIndex = null;
        } else {
            // 添加模式
            this.combinations.push(combo);
        }
        
        // 隐藏弹窗
        const modal = bootstrap.Modal.getInstance(document.getElementById('add-combo-modal'));
        modal.hide();
        
        document.getElementById('save-indicator').classList.remove('show');
        this.renderCombinations();
    },
    
    // 生成唯一ID
    generateId: function() {
        return 'combo-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
    },
    
    // 保存方案
    savePlan: async function() {
        const name = document.getElementById('plan-name-input').value.trim();
        const description = document.getElementById('plan-desc-input').value.trim();
        
        if (!name) {
            alert('请输入方案名称');
            return;
        }
        
        if (this.combinations.length === 0) {
            alert('请至少添加一个策略组合');
            return;
        }
        
        const planData = {
            name: name,
            description: description,
            combinations: this.combinations
        };
        
        try {
            let response;
            if (this.currentPlan) {
                // 更新现有方案
                response = await fetch(`/api/execution/plans/${this.currentPlan.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(planData)
                });
            } else {
                // 创建新方案
                response = await fetch('/api/execution/plans', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(planData)
                });
            }
            
            const result = await response.json();
            
            if (result.success) {
                document.getElementById('save-indicator').classList.add('show');
                
                // 如果是新建方案，更新当前方案信息
                if (!this.currentPlan) {
                    this.currentPlan = result.data;
                    document.getElementById('export-plan-btn').style.display = 'inline-block';
                    document.getElementById('delete-plan-btn').style.display = 'inline-block';
                }
                
                // 刷新方案列表
                await this.loadPlanList();
                
                // 高亮选中当前方案
                setTimeout(() => {
                    const item = document.querySelector(`[data-plan-id="${this.currentPlan.id}"]`);
                    if (item) {
                        document.querySelectorAll('.plan-list-item').forEach(i => i.classList.remove('active'));
                        item.classList.add('active');
                    }
                }, 100);
                
                alert('保存成功');
            } else {
                alert('保存失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('保存方案失败:', error);
            alert('保存方案失败');
        }
    },
    
    // 导出方案
    exportPlan: async function() {
        if (!this.currentPlan) return;
        
        try {
            const response = await fetch(`/api/execution/plans/${this.currentPlan.id}/export`);
            const blob = await response.blob();
            
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${this.currentPlan.name}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('导出方案失败:', error);
            alert('导出方案失败');
        }
    },
    
    // 删除方案
    deletePlan: async function() {
        if (!this.currentPlan) return;
        
        if (!confirm(`确定要删除方案 "${this.currentPlan.name}" 吗？此操作不可撤销。`)) {
            return;
        }
        
        try {
            const response = await fetch(`/api/execution/plans/${this.currentPlan.id}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (result.success) {
                // 重置界面
                this.createNewPlan();
                await this.loadPlanList();
                alert('删除成功');
            } else {
                alert('删除失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('删除方案失败:', error);
            alert('删除方案失败');
        }
    },
    
    // 导入方案
    importPlan: async function() {
        const fileInput = document.getElementById('import-file');
        const file = fileInput.files[0];
        
        if (!file) {
            alert('请选择要导入的方案文件');
            return;
        }
        
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            const response = await fetch('/api/execution/plans/import', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                // 关闭弹窗
                const modal = bootstrap.Modal.getInstance(document.getElementById('import-modal'));
                modal.hide();
                
                // 清空文件输入
                fileInput.value = '';
                
                // 刷新方案列表
                await this.loadPlanList();
                
                // 加载刚导入的方案
                this.loadPlan(result.data.id);
                
                alert('导入成功');
            } else {
                alert('导入失败: ' + (result.message || '未知错误'));
            }
        } catch (error) {
            console.error('导入方案失败:', error);
            alert('导入方案失败');
        }
    },
    
    // 执行方案
    runPlan: async function() {
        if (!this.currentPlan) {
            alert('请先创建或选择一个方案');
            return;
        }
        
        const initialCash = parseInt(document.getElementById('initial-cash').value) || 300000;
        const maxStocks = parseInt(document.getElementById('max-stocks').value) || 8;
        const scoreThreshold = parseInt(document.getElementById('score-threshold').value) || 60;
        
        // 更新执行状态
        document.getElementById('execution-status').className = 'execution-status status-running';
        document.getElementById('execution-status').textContent = '执行中';
        
        // 清空日志
        document.getElementById('execution-log').innerHTML = '<p class="text-muted">开始执行...</p>';
        
        try {
            const response = await fetch(`/api/execution/plans/${this.currentPlan.id}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    initial_cash: initialCash,
                    max_stocks: maxStocks,
                    score_threshold: scoreThreshold
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.appendLog('执行成功');
                this.appendLog('--- 执行结果 ---');
                this.appendLog(JSON.stringify(result.data, null, 2));
                document.getElementById('execution-status').className = 'execution-status status-idle';
                document.getElementById('execution-status').textContent = '就绪';
            } else {
                this.appendLog('执行失败: ' + (result.message || '未知错误'));
                document.getElementById('execution-status').className = 'execution-status status-error';
                document.getElementById('execution-status').textContent = '错误';
            }
        } catch (error) {
            console.error('执行方案失败:', error);
            this.appendLog('执行失败: ' + error.message);
            document.getElementById('execution-status').className = 'execution-status status-error';
            document.getElementById('execution-status').textContent = '错误';
        }
    },
    
    // 追加日志
    appendLog: function(message) {
        const logContainer = document.getElementById('execution-log');
        const timestamp = new Date().toLocaleTimeString();
        const logItem = document.createElement('div');
        logItem.innerHTML = `<span class="text-muted">[${timestamp}]</span> ${message}`;
        logContainer.appendChild(logItem);
        logContainer.scrollTop = logContainer.scrollHeight;
    }
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    ExecutionPlanModule.init();
});