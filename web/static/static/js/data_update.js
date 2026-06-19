/**
 * 数据更新页面 - 前端逻辑（超简洁版）
 * 功能：显示上次更新时间 -> 开始更新 -> 显示进度 -> 显示结果
 */

// 全局状态
let updateTaskId = null;
let updateProgressInterval = null;

/**
 * 初始化数据更新页面
 */
function initDataUpdatePage() {
    try {
        console.log('初始化数据更新页面...');
        
        // 重置全局状态
        updateTaskId = null;
        
        // 清除进度轮询
        if (updateProgressInterval) {
            clearInterval(updateProgressInterval);
            updateProgressInterval = null;
        }
        
        // 重置UI
        resetUpdateUI();
        
        // 加载上次更新时间
        loadLastUpdateTime();
        
        console.log('数据更新页面初始化完成');
    } catch (error) {
        console.error('初始化数据更新页面时出错:', error);
    }
}

/**
 * 加载上次更新时间
 */
async function loadLastUpdateTime() {
    try {
        console.log('加载上次更新时间...');
        
        const response = await fetch('/api/data/update/last-update-time');
        const result = await response.json();
        
        if (result.success) {
            const lastUpdateTime = result.data.lastUpdateTime || '-';
            const lastUpdateDate = result.data.lastUpdateDate || '-';
            
            // 格式化显示
            let displayText = '-';
            if (lastUpdateTime && lastUpdateTime !== '-') {
                displayText = lastUpdateTime;
            } else if (lastUpdateDate && lastUpdateDate !== '-') {
                displayText = lastUpdateDate;
            }
            
            // 更新UI
            const lastUpdateTimeElement = document.getElementById('last-update-time');
            if (lastUpdateTimeElement) {
                lastUpdateTimeElement.textContent = displayText;
            }
            
            console.log('上次更新时间:', displayText);
        } else {
            console.warn('获取上次更新时间失败:', result.message || result.error);
            
            // 显示默认值
            const lastUpdateTimeElement = document.getElementById('last-update-time');
            if (lastUpdateTimeElement) {
                lastUpdateTimeElement.textContent = '暂无数据';
            }
        }
    } catch (error) {
        console.error('加载上次更新时间时出错:', error);
        
        // 显示默认值
        const lastUpdateTimeElement = document.getElementById('last-update-time');
        if (lastUpdateTimeElement) {
            lastUpdateTimeElement.textContent = '暂无数据';
        }
    }
}

/**
 * 重置更新UI
 */
function resetUpdateUI() {
    try {
        // 显示初始状态
        const initialState = document.getElementById('update-initial-state');
        if (initialState) initialState.style.display = 'block';
        
        // 隐藏进度状态
        const progressState = document.getElementById('update-progress-state');
        if (progressState) progressState.style.display = 'none';
        
        // 隐藏完成状态
        const completedState = document.getElementById('update-completed-state');
        if (completedState) completedState.style.display = 'none';
    } catch (error) {
        console.error('重置更新 UI 时出错:', error);
    }
}

/**
 * 启动数据更新
 */
async function startDataUpdate() {
    try {
        console.log('用户点击了开始数据更新按钮');
        
        // 确认更新
        if (!confirm('确定要开始数据更新吗？')) {
            console.log('用户取消了数据更新');
            return;
        }
        
        console.log('发送请求到后端...');
        
        // 调用后端API启动更新
        const response = await fetch('/api/data/update/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({})
        });
        
        const result = await response.json();
        console.log('后端响应:', result);
        
        if (result.success) {
            // 获取任务ID
            updateTaskId = result.taskId;
            
            console.log('数据更新已启动，任务ID:', updateTaskId);
            
            // 隐藏初始状态
            const initialState = document.getElementById('update-initial-state');
            if (initialState) initialState.style.display = 'none';
            
            // 显示进度状态
            const progressState = document.getElementById('update-progress-state');
            if (progressState) progressState.style.display = 'block';
            
            // 开始轮询进度
            pollUpdateProgress();
        } else {
            const errorMsg = result.message || result.error || '未知错误';
            console.error('启动更新失败:', errorMsg);
            alert('启动更新失败: ' + errorMsg);
        }
    } catch (error) {
        console.error('启动更新时出错:', error);
        alert('启动更新失败: ' + error.message);
    }
}

/**
 * 轮询更新进度
 */
function pollUpdateProgress() {
    // 清除之前的轮询
    if (updateProgressInterval) {
        clearInterval(updateProgressInterval);
    }
    
    // 立即获取一次进度
    getUpdateProgress();
    
    // 每500ms轮询一次进度
    updateProgressInterval = setInterval(getUpdateProgress, 500);
}

/**
 * 获取更新进度
 */
async function getUpdateProgress() {
    if (!updateTaskId) {
        console.warn('没有任务ID，无法获取进度');
        return;
    }
    
    try {
        const url = `/api/data/update/progress?taskId=${updateTaskId}`;
        const response = await fetch(url);
        const result = await response.json();
        
        if (result.success) {
            // 更新进度UI
            updateProgressUI(result.data);
            
            // 根据状态判断是否完成
            const status = result.data.status;
            if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                console.log('更新已完成，状态:', status);
                
                if (updateProgressInterval) {
                    clearInterval(updateProgressInterval);
                    updateProgressInterval = null;
                }
                
                // 显示完成状态
                showUpdateCompleted(result.data);
            }
        } else {
            console.error('获取进度失败:', result.message || result.error);
        }
    } catch (error) {
        console.error('获取更新进度时出错:', error);
    }
}

/**
 * 更新进度UI
 */
function updateProgressUI(data) {
    try {
        // 简洁版本：只显示"正在更新中"，不显示进度条
        // 但在控制台输出详细信息用于调试
        console.log('更新进度:', {
            status: data.status,
            progress: data.progress,
            message: data.message,
            totalStats: data.totalStats
        });
    } catch (error) {
        console.error('更新进度 UI 时出错:', error);
    }
}

/**
 * 取消数据更新
 */
async function cancelDataUpdate() {
    if (!updateTaskId) {
        alert('没有正在运行的更新任务');
        return;
    }
    
    if (!confirm('确定要取消数据更新吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/data/update/cancel?taskId=${updateTaskId}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 停止轮询进度
            if (updateProgressInterval) {
                clearInterval(updateProgressInterval);
                updateProgressInterval = null;
            }
            
            // 重置UI状态
            resetUpdateUI();
            
            alert('✓ 数据更新已取消');
        } else {
            alert('取消更新失败: ' + (result.message || '未知错误'));
        }
    } catch (error) {
        alert('取消更新失败: ' + error.message);
    }
}

/**
 * 显示更新完成
 */
function showUpdateCompleted(data) {
    try {
        // 隐藏进度状态
        const progressState = document.getElementById('update-progress-state');
        if (progressState) progressState.style.display = 'none';
        
        // 显示完成状态
        const completedState = document.getElementById('update-completed-state');
        if (completedState) completedState.style.display = 'block';
        
        // 根据状态显示不同的完成信息
        if (data.status === 'completed') {
            // 成功完成
            const stats = data.totalStats || {};
            
            // 提取统计数据
            const klineAdded = stats.kline_added || 0;
            const klineUpdated = stats.kline_updated || 0;
            const fundFlowAdded = stats.fund_flow_added || 0;
            const fundFlowUpdated = stats.fund_flow_updated || 0;
            
            // 计算总数
            const totalAdded = klineAdded + fundFlowAdded;
            const totalUpdated = klineUpdated + fundFlowUpdated;
            const total = totalAdded + totalUpdated;
            
            // 更新统计数据
            document.getElementById('update-result-added').textContent = totalAdded;
            document.getElementById('update-result-updated').textContent = totalUpdated;
            document.getElementById('update-result-total').textContent = total;
            
            console.log('更新完成，统计信息:', {
                klineAdded,
                klineUpdated,
                fundFlowAdded,
                fundFlowUpdated,
                totalAdded,
                totalUpdated,
                total
            });
            
            // 刷新首页统计信息
            loadStats();
        } else if (data.status === 'failed') {
            // 失败
            document.getElementById('update-result-icon').textContent = '⚠️';
            
            // 显示错误信息
            const errorMsg = data.message || data.error || '未知错误';
            console.error('更新失败:', errorMsg);
            
            // 更新文本
            document.getElementById('update-result-text').textContent = `数据更新失败: ${errorMsg}`;
            document.getElementById('update-result-text').style.color = '#ef4444';
            
            // 添加错误详情
            const statsDiv = document.getElementById('update-result-stats');
            if (statsDiv) {
                statsDiv.innerHTML = `<div style="color: #ef4444; padding: 10px; background: #fee2e2; border-radius: 4px;">错误: ${errorMsg}</div>`;
            }
        } else if (data.status === 'cancelled') {
            // 已取消
            document.getElementById('update-result-icon').textContent = '⊘';
            document.getElementById('update-result-text').textContent = '数据更新已取消';
            document.getElementById('update-result-text').style.color = '#6b7280';
        }
    } catch (error) {
        console.error('显示完成状态时出错:', error);
    }
}
