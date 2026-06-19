/**
 * WebSocket相关功能模块
 */

// WebSocket连接
let socket = null;
let updateStatusInterval = null;

/**
 * 初始化WebSocket连接
 */
export function initWebSocket() {
    // 创建Socket.IO连接
    socket = io();
    
    // 监听更新进度事件
    socket.on('update_progress', function(data) {
        console.log('收到更新进度:', data);
        updateProgressUI(data);
    });
    
    // 监听初始化进度事件
    socket.on('init_progress', function(data) {
        console.log('收到初始化进度:', data);
        updateInitProgressUI(data);
    });
    
    // 连接成功
    socket.on('connect', function() {
        console.log('WebSocket已连接');
    });
    
    // 连接断开
    socket.on('disconnect', function() {
        console.log('WebSocket已断开');
    });
    
    // 连接错误
    socket.on('connect_error', function(error) {
        console.error('WebSocket连接错误:', error);
    });
}

/**
 * 更新进度UI
 * @param {Object} status - 进度状态
 */
export function updateProgressUI(status) {
    const progressCard = document.getElementById('update-progress-card');
    if (!progressCard) return;
    
    // 显示进度卡片
    progressCard.style.display = 'block';
    
    // 计算进度百分比
    const progress = status.total > 0 ? Math.round((status.success / status.total) * 100) : 0;
    
    // 更新UI
    const progressFill = document.getElementById('progress-fill');
    const progressPercent = document.getElementById('progress-percent');
    const progressText = document.getElementById('progress-text');
    const updateSuccess = document.getElementById('update-success');
    const updateFailed = document.getElementById('update-failed');
    const updateMessage = document.getElementById('update-message');
    
    if (progressFill) progressFill.style.width = progress + '%';
    if (progressPercent) progressPercent.textContent = progress + '%';
    if (progressText) progressText.textContent = status.message || '正在更新...';
    if (updateSuccess) updateSuccess.textContent = status.success || 0;
    if (updateFailed) updateFailed.textContent = status.failed || 0;
    if (updateMessage) updateMessage.textContent = status.message || '';
    
    // 如果更新完成
    if (!status.running && status.start_time) {
        // 清除轮询（如果使用的话）
        if (updateStatusInterval) {
            clearInterval(updateStatusInterval);
            updateStatusInterval = null;
        }
        
        // 显示完成信息
        setTimeout(() => {
            // 检查是否有详细统计信息
            let message = `数据更新完成!\n成功: ${status.success}\n失败: ${status.failed}`;
            
            // 如果有详细统计，显示更多信息
            if (status.totalStats) {
                const stats = status.totalStats;
                const klineFailed = stats.kline_failed || 0;
                const fundFlowFailed = stats.fund_flow_failed || 0;
                const totalFailed = klineFailed + fundFlowFailed;
                
                message = `数据更新${status.success ? '完成' : '失败'}!\n`;
                message += `K线数据: 新增 ${stats.kline_added || 0} 条, 更新 ${stats.kline_updated || 0} 条, 失败 ${klineFailed} 条\n`;
                message += `资金流向: 新增 ${stats.fund_flow_added || 0} 条, 更新 ${stats.fund_flow_updated || 0} 条, 失败 ${fundFlowFailed} 条\n`;
                
                // 如果失败数量超过1000，显示警告
                if (totalFailed > 1000) {
                    message += `\n⚠️ 警告: 失败股票数量(${totalFailed})超过1000，当日数据可能不完整，请重新更新!`;
                }
            }
            
            alert(message);
            progressCard.style.display = 'none';
            // 刷新统计信息
            import('./stocks.js').then(module => module.loadStats());
        }, 1000);
    }
}

/**
 * 更新初始化进度UI
 * @param {Object} data - 初始化进度数据
 */
function updateInitProgressUI(data) {
    console.log('初始化进度:', data);
    // 可以根据需要实现初始化进度的UI更新
}

/**
 * 检查更新状态（备用方案，当WebSocket不可用时使用）
 * @param {HTMLElement} progressCard - 进度卡片元素
 */
export async function checkUpdateStatusBackup(progressCard) {
    // 如果已有WebSocket连接，减少轮询频率
    const pollInterval = socket && socket.connected ? 5000 : 1000;
    
    updateStatusInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/update/status');
            const result = await response.json();
            
            if (result.success) {
                const status = result.status;
                
                // 更新进度显示
                const progress = status.total > 0 ? Math.round((status.success / status.total) * 100) : 0;
                document.getElementById('progress-fill').style.width = progress + '%';
                document.getElementById('progress-percent').textContent = progress + '%';
                document.getElementById('progress-text').textContent = status.message;
                document.getElementById('update-success').textContent = status.success;
                document.getElementById('update-failed').textContent = status.failed;
                document.getElementById('update-message').textContent = status.message;
                
                // 如果更新完成
                if (!status.running) {
                    clearInterval(updateStatusInterval);
                    updateStatusInterval = null;
                    
                    // 显示完成信息
                    setTimeout(() => {
                        alert(`Data update completed!\nSuccess: ${status.success}\nFailed: ${status.failed}`);
                        progressCard.style.display = 'none';
                        // 刷新统计信息
                        import('./stocks.js').then(module => module.loadStats());
                    }, 1000);
                }
            }
        } catch (error) {
            console.error('Check update status failed:', error);
        }
    }, pollInterval);
}
