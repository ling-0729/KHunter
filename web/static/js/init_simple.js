/**
 * 超简洁版初始化数据页面 JavaScript
 * 功能：选择初始化范围 -> 初始化中 -> 显示结果
 * 
 * 注意：此文件中的函数与 app.js 中的函数配合使用
 * 避免重复定义，使用不同的函数名
 * 依赖 app.js 中已定义的 initState 对象
 */

/**
 * 开始初始化
 */
function startInitialization() {
    try {
        console.log('用户点击了开始初始化按钮');
        
        // 确认初始化
        if (!confirm('确定要开始数据初始化吗？这可能需要较长时间。')) {
            console.log('用户取消了初始化');
            return;
        }
        
        // 获取初始化选项
        const initBasicData = document.getElementById('init-basic-data').checked;
        const initHistoryData = document.getElementById('init-history-data').checked;
        const initIndustryData = document.getElementById('init-industry-data').checked;
        const initSectorData = document.getElementById('init-sector-data').checked;
        const initFundFlowData = document.getElementById('init-fund-flow-data').checked;
        
        // 检查是否至少选择了一项
        if (!initBasicData && !initHistoryData && !initIndustryData && !initSectorData && !initFundFlowData) {
            alert('请至少选择一项初始化数据');
            return;
        }
        
        // 构建初始化选项
        const options = {
            basicData: initBasicData,
            historyData: initHistoryData,
            industryData: initIndustryData,
            sectorData: initSectorData,
            fundFlowData: initFundFlowData
        };
        
        console.log('发送初始化请求到后端...');
        console.log('初始化选项:', options);
        
        // 调用后端API启动初始化
        fetch('/api/data/init/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                type: 'custom',
                options: options
            })
        })
        .then(response => response.json())
        .then(result => {
            console.log('后端响应:', result);
            
            if (result.success) {
                // 获取任务ID
                const taskId = result.taskId;
                console.log('初始化已启动，任务ID:', taskId);
                
                // 隐藏初始状态，显示进度状态
                document.getElementById('init-step1').style.display = 'none';
                document.getElementById('init-step2').style.display = 'block';
                
                // 开始轮询进度
                pollInitProgress();
            } else {
                const errorMsg = result.message || '未知错误';
                console.error('启动初始化失败:', errorMsg);
                alert('启动初始化失败: ' + errorMsg);
            }
        })
        .catch(error => {
            console.error('启动初始化时出错:', error);
            alert('启动初始化失败: ' + error.message);
        });
    } catch (error) {
        console.error('开始初始化时出错:', error);
        alert('启动初始化失败: ' + error.message);
    }
}

/**
 * 轮询初始化进度
 */
function pollInitProgress() {
    // 立即获取一次进度
    getInitProgress();
    
    // 每1000ms轮询一次进度
    const intervalId = setInterval(() => {
        getInitProgress(intervalId);
    }, 1000);
}

/**
 * 获取初始化进度
 */
async function getInitProgress(intervalId) {
    try {
        const url = '/api/data/init/progress';
        const response = await fetch(url);
        const result = await response.json();
        
        if (result.success) {
            // 更新进度UI
            updateInitProgressDisplay(result.data);
            
            // 根据状态判断是否完成
            const status = result.data.status;
            if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                console.log('初始化已完成，状态:', status);
                
                // 清除轮询
                if (intervalId) {
                    clearInterval(intervalId);
                }
                
                // 显示完成状态
                if (status === 'completed') {
                    showInitCompletionStep(result.data);
                } else if (status === 'failed') {
                    showInitError(result.data);
                } else if (status === 'cancelled') {
                    resetInitForm();
                }
            }
        } else {
            console.error('获取进度失败:', result.message || result.error);
        }
    } catch (error) {
        console.error('获取初始化进度时出错:', error);
    }
}

/**
 * 取消初始化
 */
async function cancelInitialization() {
    if (!confirm('确定要取消数据初始化吗？')) {
        return;
    }
    
    try {
        const response = await fetch('/api/data/init/cancel', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            alert('✓ 初始化已取消');
            resetInitForm();
        } else {
            alert('取消初始化失败: ' + (result.message || '未知错误'));
        }
    } catch (error) {
        alert('取消初始化失败: ' + error.message);
    }
}

/**
 * 开始强制重新初始化
 */
function startReinit() {
    try {
        console.log('用户点击了重新初始化按钮');
        
        if (!confirm('⚠️ 警告：重新初始化将删除所有现有数据（基础数据 + K线数据）！\n\n确定要继续吗？')) {
            console.log('用户取消了重新初始化');
            return;
        }
        
        if (!confirm('再次确认：所有现有数据将被删除，确定要重新初始化吗？')) {
            console.log('用户取消了重新初始化');
            return;
        }
        
        console.log('发送重新初始化请求...');
        
        fetch('/api/data/reinit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({})
        })
        .then(response => response.json())
        .then(result => {
            console.log('后端响应:', result);
            
            if (result.success) {
                const taskId = result.taskId;
                console.log('重新初始化已启动，任务ID:', taskId);
                
                document.getElementById('init-step1').style.display = 'none';
                document.getElementById('init-step2').style.display = 'block';
                
                pollInitProgress();
            } else {
                alert('启动重新初始化失败: ' + (result.message || '未知错误'));
            }
        })
        .catch(error => {
            console.error('启动重新初始化时出错:', error);
            alert('启动重新初始化失败: ' + error.message);
        });
    } catch (error) {
        console.error('开始重新初始化时出错:', error);
        alert('启动重新初始化失败: ' + error.message);
    }
}

/**
 * 重置初始化表单
 */
function resetInitForm() {
    // 显示初始状态，隐藏其他状态
    document.getElementById('init-step1').style.display = 'block';
    document.getElementById('init-step2').style.display = 'none';
    document.getElementById('init-step3').style.display = 'none';
}

/**
 * 返回初始化步骤1
 */
function backToInitStep1() {
    resetInitForm();
}

/**
 * 注册 WebSocket 监听器（备用方式，确保能够及时收到完成状态）
 */
function setupInitWebSocketListener() {
    // 注册 WebSocket 监听器（备用方式，确保能够及时收到完成状态）
    if (typeof socket !== 'undefined' && socket) {
        // 移除旧的监听器（如果存在）
        socket.off('init_progress');
        // 添加新的监听器
        socket.on('init_progress', function(data) {
            console.log('WebSocket 收到初始化进度:', data);
            handleWebSocketInitProgress(data);
        });
        console.log('已注册 WebSocket 初始化进度监听器');
    }
}

/**
 * 处理 WebSocket 初始化进度事件
 * 这是一个备用方式，确保能够及时收到完成状态
 */
function handleWebSocketInitProgress(data) {
    if (!initState.isRunning) {
        return;
    }
    
    console.log('WebSocket 初始化进度:', data.status, data.progress, '%', data.currentTask);
    
    // 动态更新当前任务显示
    updateInitProgressDisplay(data);
    
    // 根据状态处理
    if (data.status === 'completed') {
        console.log('WebSocket: 初始化完成');
        initState.isRunning = false;
        showInitCompletionStep(data);
    } else if (data.status === 'failed') {
        console.log('WebSocket: 初始化失败');
        initState.isRunning = false;
        showInitError(data);
    } else if (data.status === 'cancelled') {
        console.log('WebSocket: 初始化已取消');
        initState.isRunning = false;
        resetInitForm();
    }
}

/**
 * 动态更新初始化进度显示
 */
function updateInitProgressDisplay(data) {
    // 更新步骤2的标题，显示当前任务
    const step2Header = document.querySelector('#init-step2 .card-header h3');
    if (step2Header && data.currentTask) {
        step2Header.textContent = `⏳ ${data.currentTask}`;
    }
    
    // 更新步骤2的内容，显示进度百分比和详细信息
    const step2Body = document.querySelector('#init-step2 .card-body');
    if (step2Body) {
        // 查找或创建进度显示元素
        let progressDisplay = document.getElementById('init-progress-display');
        if (!progressDisplay) {
            progressDisplay = document.createElement('div');
            progressDisplay.id = 'init-progress-display';
            progressDisplay.style.cssText = 'text-align: center; padding: 20px; margin-bottom: 20px;';
            step2Body.insertBefore(progressDisplay, step2Body.firstChild);
        }
        
        // 计算进度条宽度
        const progress = data.progress || 0;
        const progressBarWidth = Math.min(progress, 100);
        
        // 更新进度显示
        progressDisplay.innerHTML = `
            <div style="font-size: 48px; margin-bottom: 10px;">⏳</div>
            <p style="font-size: 16px; color: #6b7280; margin: 10px 0;">
                ${data.currentTask || '初始化进行中'}
            </p>
            <div style="font-size: 28px; font-weight: 600; color: #0284c7; margin: 15px 0;">
                ${progress}%
            </div>
            
            <!-- 进度条 -->
            <div style="width: 100%; height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden; margin: 15px 0;">
                <div style="width: ${progressBarWidth}%; height: 100%; background: linear-gradient(90deg, #0284c7, #06b6d4); transition: width 0.3s ease;"></div>
            </div>
            
            <!-- 详细信息 -->
            <div style="font-size: 12px; color: #9ca3af; margin-top: 10px;">
                ${data.message || ''}
            </div>
        `;
    }
}

/**
 * 显示初始化完成步骤
 */
function showInitCompletionStep(data) {
    // 隐藏进度步骤，显示完成步骤
    const step2 = document.getElementById('init-step2');
    const step3 = document.getElementById('init-step3');
    
    if (step2) step2.style.display = 'none';
    if (step3) step3.style.display = 'block';
    
    // 设置完成状态
    const stats = data.statistics || {};
    const success = stats.success || 0;
    const failed = stats.failed || 0;
    
    // 根据是否有失败来设置图标和文本
    const statusIcon = document.getElementById('init-status-icon');
    const statusText = document.getElementById('init-status-text');
    const resultTitle = document.getElementById('init-result-title');
    
    if (failed > 0) {
        if (statusIcon) statusIcon.textContent = '⚠️';
        if (statusText) {
            statusText.textContent = '初始化完成（有失败）';
            statusText.style.color = '#f59e0b';
        }
        if (resultTitle) resultTitle.textContent = '⚠️ 初始化完成';
    } else {
        if (statusIcon) statusIcon.textContent = '✓';
        if (statusText) {
            statusText.textContent = '初始化成功！';
            statusText.style.color = '#10b981';
        }
        if (resultTitle) resultTitle.textContent = '✅ 初始化完成';
    }
    
    // 生成统计卡片
    const statsContainer = document.getElementById('init-result-stats');
    if (statsContainer) {
        statsContainer.innerHTML = '';
        
        // 成功数量
        const successCard = document.createElement('div');
        successCard.style.cssText = 'padding: 15px; background: #f0fdf4; border-radius: 6px; text-align: center;';
        successCard.innerHTML = `
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px;">成功数量</div>
            <div style="font-size: 24px; font-weight: 600; color: #10b981;">${success}</div>
        `;
        statsContainer.appendChild(successCard);
        
        // 失败数量
        const failedCard = document.createElement('div');
        failedCard.style.cssText = 'padding: 15px; background: #fee2e2; border-radius: 6px; text-align: center;';
        failedCard.innerHTML = `
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px;">失败数量</div>
            <div style="font-size: 24px; font-weight: 600; color: #ef4444;">${failed}</div>
        `;
        statsContainer.appendChild(failedCard);
        
        // 总数量
        const totalCard = document.createElement('div');
        totalCard.style.cssText = 'padding: 15px; background: #f0f9ff; border-radius: 6px; text-align: center;';
        totalCard.innerHTML = `
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px;">总数量</div>
            <div style="font-size: 24px; font-weight: 600; color: #0284c7;">${success + failed}</div>
        `;
        statsContainer.appendChild(totalCard);
    }
}

/**
 * 显示初始化错误
 */
function showInitError(data) {
    // 隐藏进度步骤，显示完成步骤
    const step2 = document.getElementById('init-step2');
    const step3 = document.getElementById('init-step3');
    
    if (step2) step2.style.display = 'none';
    if (step3) step3.style.display = 'block';
    
    // 设置错误状态
    const statusIcon = document.getElementById('init-status-icon');
    const statusText = document.getElementById('init-status-text');
    const resultTitle = document.getElementById('init-result-title');
    
    if (statusIcon) statusIcon.textContent = '✗';
    if (statusText) {
        statusText.textContent = '初始化失败';
        statusText.style.color = '#ef4444';
    }
    if (resultTitle) resultTitle.textContent = '✗ 初始化失败';
    
    // 显示错误信息
    const statsContainer = document.getElementById('init-result-stats');
    if (statsContainer) {
        statsContainer.innerHTML = '';
        
        const errorCard = document.createElement('div');
        errorCard.style.cssText = 'padding: 15px; background: #fee2e2; border-radius: 6px; width: 100%;';
        errorCard.innerHTML = `
            <div style="font-size: 12px; color: #6b7280; margin-bottom: 8px;">错误信息</div>
            <div style="font-size: 14px; color: #ef4444; word-break: break-all;">${data.message || '未知错误'}</div>
        `;
        statsContainer.appendChild(errorCard);
    }
}

/**
 * 页面加载时初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    // 初始化完成
    console.log('超简洁版初始化页面已加载');
    
    // 注册全局 WebSocket 监听器（备用方式）
    // 这确保即使 HTTP 轮询失败，也能通过 WebSocket 收到完成状态
    if (typeof socket !== 'undefined' && socket) {
        socket.on('init_progress', function(data) {
            console.log('全局 WebSocket 初始化进度监听器:', data);
            if (initState && initState.isRunning) {
                handleWebSocketInitProgress(data);
            }
        });
        console.log('已注册全局 WebSocket 初始化进度监听器');
    }
});
