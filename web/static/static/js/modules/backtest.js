/**
 * 回测模块相关功能
 */

// 全局变量
let backtestConfig = {
    strategy_name: '',
    start_date: '',
    end_date: '',
    initial_capital: 1000000,
    score_threshold: 60,
    buy_amount: 100000,
    max_daily_buys: 5,
    support_level_method: 'ma20',
    stop_loss: 0.05,
    take_profit: 0.15,
    max_hold_days: 10
};

/**
 * 初始化回测配置页面
 */
export function initBacktestConfigPage() {
    console.log('初始化回测配置页面');
    
    // 加载策略列表
    loadStrategies();
    
    // 绑定表单事件
    bindConfigFormEvents();
    
    // 初始化日期选择器
    initDatePickers();
}

/**
 * 初始化回测参数配置页面
 */
export function initBacktestParamsPage() {
    console.log('初始化回测参数配置页面');
    
    // 加载保存的配置
    loadBacktestParams();
    
    // 绑定表单事件
    bindParamsFormEvents();
}

/**
 * 初始化回测结果页面
 */
export function initBacktestResultsPage() {
    console.log('初始化回测结果页面');
    
    // 显示默认提示
    showResultsEmptyState('请先运行回测以查看结果');
}

/**
 * 初始化回测历史页面
 */
export function initBacktestHistoryPage() {
    console.log('初始化回测历史页面');
    
    // 加载策略列表
    loadHistoryStrategies();
    
    // 加载历史回测记录
    loadBacktestHistory();
}

/**
 * 加载回测历史页面的策略列表（参考选股历史页面实现）
 */
async function loadHistoryStrategies() {
    try {
        console.log('loadHistoryStrategies 开始执行');
        // 使用与选股历史页面相同的策略接口
        const response = await fetch('/api/strategies');
        console.log('API 响应状态:', response.status);
        if (!response.ok) {
            throw new Error('加载策略列表失败: ' + response.status);
        }
        const data = await response.json();
        console.log('API 返回数据:', data);
        
        // 查找正确的元素 ID
        const strategySelect = document.getElementById('backtest-history-strategy-filter');
        console.log('strategySelect 元素:', strategySelect);
        
        if (strategySelect) {
            // 保留原有的"全部策略"选项，追加API返回的策略
            const existingOptions = Array.from(strategySelect.options);
            const optionsToKeep = existingOptions.slice(0, 1); // 保留第一个选项（全部策略）
            
            strategySelect.innerHTML = '';
            optionsToKeep.forEach(opt => strategySelect.appendChild(opt));
            
            if (data.success && data.data && data.data.length > 0) {
                data.data.forEach(strategy => {
                    const strategyName = strategy.display_name || strategy.name;
                    const option = document.createElement('option');
                    option.value = strategyName;
                    option.textContent = strategyName;
                    strategySelect.appendChild(option);
                });
                console.log('回测历史策略列表加载成功, 共', data.data.length, '个策略');
            } else {
                console.warn('API 返回数据为空或格式不正确:', data.message);
            }
        } else {
            console.warn('未找到 backtest-history-strategy-filter 元素');
        }
    } catch (error) {
        console.error('加载回测历史策略列表失败:', error);
    }
}

/**
 * 加载策略列表
 */
async function loadStrategies() {
    try {
        const response = await fetch('/api/trading/backtest/strategies');
        if (!response.ok) {
            throw new Error('加载策略列表失败');
        }
        const data = await response.json();
        if (data.success) {
            const strategies = data.data.strategies;
            const strategySelect = document.getElementById('strategy-select');
            if (strategySelect) {
                strategySelect.innerHTML = '';
                strategies.forEach(strategy => {
                    const option = document.createElement('option');
                    option.value = strategy.name;
                    option.textContent = strategy.display_name || strategy.name;
                    strategySelect.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('加载策略列表失败:', error);
        alert('加载策略列表失败，请刷新页面重试');
    }
}

/**
 * 绑定配置表单事件
 */
function bindConfigFormEvents() {
    const runBacktestBtn = document.getElementById('run-backtest-btn');
    if (runBacktestBtn) {
        runBacktestBtn.addEventListener('click', async () => {
            await runBacktest();
        });
    }
}

/**
 * 绑定参数表单事件
 */
function bindParamsFormEvents() {
    const saveBacktestParamsBtn = document.getElementById('save-backtest-params-btn');
    if (saveBacktestParamsBtn) {
        saveBacktestParamsBtn.addEventListener('click', saveBacktestParams);
    }
}

/**
 * 保存回测配置
 */
async function saveBacktestParams() {
    try {
        // 收集配置数据
        const initialCapitalInput = document.getElementById('params-initial-capital');
        const scoreThresholdInput = document.getElementById('params-score-threshold');
        const buyAmountInput = document.getElementById('params-buy-amount');
        const maxDailyBuysInput = document.getElementById('params-max-daily-buys');
        const stopLossInput = document.getElementById('params-stop-loss');
        const takeProfitInput = document.getElementById('params-take-profit');
        const maxHoldDaysInput = document.getElementById('params-max-hold-days');
        
        const params = {
            config_name: '默认配置',
            score_threshold: parseFloat(scoreThresholdInput?.value) || 60,
            hold_period: parseInt(maxHoldDaysInput?.value) || 10,
            stop_loss: parseFloat(stopLossInput?.value) * 100, // 转换为百分比
            take_profit: parseFloat(takeProfitInput?.value) * 100, // 转换为百分比
            initial_capital: parseFloat(initialCapitalInput?.value) || 1000000,
            buy_amount: parseFloat(buyAmountInput?.value) || 100000,
            max_daily_buys: parseInt(maxDailyBuysInput?.value) || 5
        };
        
        // 调用后端API保存配置
        const response = await fetch('/api/trading/backtest/configs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        if (!response.ok) {
            throw new Error('保存回测配置失败');
        }
        
        const data = await response.json();
        if (data.success) {
            alert('回测配置保存成功');
        } else {
            throw new Error(data.message || '保存回测配置失败');
        }
    } catch (error) {
        console.error('保存回测配置失败:', error);
        alert('保存回测配置失败: ' + error.message);
    }
}

/**
 * 加载回测配置
 */
async function loadBacktestParams() {
    try {
        // 从后端API加载配置
        const response = await fetch('/api/trading/backtest/configs');
        if (!response.ok) {
            throw new Error('加载回测配置失败');
        }
        
        const data = await response.json();
        if (data.success && data.data.configs && data.data.configs.length > 0) {
            // 使用最新的配置
            const params = data.data.configs[0];
            
            // 填充表单
            const initialCapitalInput = document.getElementById('params-initial-capital');
            const scoreThresholdInput = document.getElementById('params-score-threshold');
            const buyAmountInput = document.getElementById('params-buy-amount');
            const maxDailyBuysInput = document.getElementById('params-max-daily-buys');
            const stopLossInput = document.getElementById('params-stop-loss');
            const takeProfitInput = document.getElementById('params-take-profit');
            const maxHoldDaysInput = document.getElementById('params-max-hold-days');
            
            if (initialCapitalInput) initialCapitalInput.value = params.initial_capital || 1000000;
            if (scoreThresholdInput) scoreThresholdInput.value = params.score_threshold || 60;
            if (buyAmountInput) buyAmountInput.value = params.buy_amount || 100000;
            if (maxDailyBuysInput) maxDailyBuysInput.value = params.max_daily_buys || 5;
            if (stopLossInput) stopLossInput.value = (params.stop_loss || -5) / 100; // 转换为小数
            if (takeProfitInput) takeProfitInput.value = (params.take_profit || 15) / 100; // 转换为小数
            if (maxHoldDaysInput) maxHoldDaysInput.value = params.hold_period || 10;
        }
    } catch (error) {
        console.error('加载回测配置失败:', error);
    }
}

/**
 * 初始化日期选择器
 */
function initDatePickers() {
    // 设置默认日期范围为最近3个月
    const endDate = new Date();
    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - 3);
    
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    
    if (startDateInput) {
        startDateInput.value = startDate.toISOString().split('T')[0];
    }
    
    if (endDateInput) {
        endDateInput.value = endDate.toISOString().split('T')[0];
    }
}

/**
 * 运行回测
 */
async function runBacktest() {
    try {
        // 收集表单数据
        const strategySelect = document.getElementById('strategy-select');
        const startDateInput = document.getElementById('start-date');
        const endDateInput = document.getElementById('end-date');
        const supportLevelSelect = document.getElementById('support-level');
        const backtestEngineSelect = document.getElementById('backtest-engine');
        
        // 验证表单数据
        if (!strategySelect?.value || !startDateInput?.value || !endDateInput?.value) {
            alert('请填写完整的回测执行条件');
            return;
        }
        
        // 加载保存的回测配置
        let savedParams = {  
            initial_capital: 1000000,
            score_threshold: 60,
            buy_amount: 100000,
            max_daily_buys: 5,
            stop_loss: 0.05,
            take_profit: 0.15,
            max_hold_days: 10
        };
        
        // 从后端API加载配置
        try {
            const response = await fetch('/api/trading/backtest/configs');
            if (response.ok) {
                const data = await response.json();
                if (data.success && data.data.configs && data.data.configs.length > 0) {
                    const config = data.data.configs[0];
                    savedParams = {
                        initial_capital: config.initial_capital || 1000000,
                        score_threshold: config.score_threshold || 60,
                        buy_amount: config.buy_amount || 100000,
                        max_daily_buys: config.max_daily_buys || 5,
                        stop_loss: (config.stop_loss || -5) / 100, // 转换为小数
                        take_profit: (config.take_profit || 15) / 100, // 转换为小数
                        max_hold_days: config.hold_period || 10
                    };
                }
            }
        } catch (error) {
            console.error('加载回测配置失败:', error);
        }
        
        // 生成配置名称
        const configName = `${strategySelect?.value || '未知策略'}_${startDateInput?.value || ''}_${endDateInput?.value || ''}`;
        
        backtestConfig = {
            config_name: configName,
            strategy_name: strategySelect?.value || '',
            start_date: startDateInput?.value || '',
            end_date: endDateInput?.value || '',
            initial_capital: savedParams.initial_capital,
            score_threshold: savedParams.score_threshold,
            buy_amount: savedParams.buy_amount,
            max_daily_buys: savedParams.max_daily_buys,
            support_level_method: supportLevelSelect?.value || 'ma20',
            stop_loss: savedParams.stop_loss * 100, // 转换为百分比
            take_profit: savedParams.take_profit * 100, // 转换为百分比
            max_hold_days: savedParams.max_hold_days
        };
        
        // 显示加载状态
        const runBacktestBtn = document.getElementById('run-backtest-btn');
        if (runBacktestBtn) {
            runBacktestBtn.disabled = true;
            runBacktestBtn.textContent = '运行中...';
        }
        
        // 运行回测
        const response = await fetch('/api/trading/backtest/run', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(backtestConfig)
        });
        
        if (!response.ok) {
            throw new Error('运行回测失败');
        }
        
        const data = await response.json();
        if (data.success) {
            // 直接在当前页面展示回测结果
            const result = data.data;
            displayBacktestResultOnConfigPage(result);
            
            // 直接使用返回的交易记录数据，无需再次调用API
            if (result.trades && result.trades.length > 0) {
                displayBacktestTradesOnConfigPage(result.trades);
            } else {
                // 如果没有交易记录，显示空状态
                const tradesBody = document.getElementById('backtest-trades-body');
                if (tradesBody) {
                    tradesBody.innerHTML = '<tr><td colspan="6" class="text-center">暂无交易记录</td></tr>';
                }
            }
        } else {
            throw new Error(data.message || '运行回测失败');
        }
    } catch (error) {
        console.error('运行回测失败:', error);
        alert('运行回测失败: ' + error.message);
    } finally {
        // 恢复按钮状态
        const runBacktestBtn = document.getElementById('run-backtest-btn');
        if (runBacktestBtn) {
            runBacktestBtn.disabled = false;
            runBacktestBtn.textContent = '运行回测';
        }
    }
}

/**
 * 加载回测结果
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestResult(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}`);
        if (!response.ok) {
            throw new Error('加载回测结果失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const result = data.data;
            displayBacktestResult(result);
            
            // 绘制收益曲线
            if (result.equity_curve) {
                const capitalHistory = result.equity_curve.map(item => item.capital);
                const dates = result.equity_curve.map(item => item.date);
                drawEquityChart(capitalHistory, dates);
            }
            
            // 加载交易记录
            loadBacktestTrades(resultId);
        } else {
            throw new Error(data.message || '加载回测结果失败');
        }
    } catch (error) {
        console.error('加载回测结果失败:', error);
        showResultsEmptyState('加载回测结果失败: ' + error.message);
    }
}

/**
 * 显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResult(result) {
    const resultsContainer = document.getElementById('backtest-results-container');
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>回测结果</h3>
                </div>
                <div class="card-body">
                    <div class="grid grid-cols-2 gap-4">
                        <div class="form-group">
                            <label>策略名称</label>
                            <input type="text" value="${result.strategy_name || ''}" disabled>
                        </div>
                        <div class="form-group">
                            <label>回测期间</label>
                            <input type="text" value="${result.start_date || ''} 至 ${result.end_date || ''}" disabled>
                        </div>
                        <div class="form-group">
                            <label>支撑位置计算方法</label>
                            <input type="text" value="${result.support_level_method || ''}" disabled>
                        </div>
                        <div class="form-group">
                            <label>初始资金</label>
                            <input type="text" value="${result.initial_capital || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>最终资金</label>
                            <input type="text" value="${(result.final_capital || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>总收益率</label>
                            <input type="text" value="${(result.total_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>胜率</label>
                            <input type="text" value="${(result.win_rate || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>平均收益率</label>
                            <input type="text" value="${(result.avg_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>盈亏比</label>
                            <input type="text" value="${(result.profit_loss_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>最大回撤</label>
                            <input type="text" value="${(result.max_drawdown || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>夏普比率</label>
                            <input type="text" value="${(result.sharpe_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>波动率</label>
                            <input type="text" value="${(result.volatility || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group">
                            <label>索提诺比率</label>
                            <input type="text" value="${(result.sortino_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group">
                            <label>总交易次数</label>
                            <input type="text" value="${result.total_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>盈利交易次数</label>
                            <input type="text" value="${result.winning_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>亏损交易次数</label>
                            <input type="text" value="${result.losing_trades || 0}" disabled>
                        </div>
                        <div class="form-group">
                            <label>平均持有天数</label>
                            <input type="text" value="${(result.avg_hold_days || 0).toFixed(2)}" disabled>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

/**
 * 加载回测交易记录
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTrades(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTrades(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 显示回测交易记录
 * @param {Array} trades - 交易记录数组
 */
function displayBacktestTrades(trades) {
    const tradesContainer = document.getElementById('backtest-trades-container');
    if (tradesContainer) {
        if (trades.length === 0) {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <p class="text-center">暂无交易记录</p>
                    </div>
                </div>
            `;
        } else {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <div class="overflow-x-auto">
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>股票代码</th>
                                        <th>股票名称</th>
                                        <th>买入日期</th>
                                        <th>买入价格</th>
                                        <th>卖出日期</th>
                                        <th>卖出价格</th>
                                        <th>收益率</th>
                                        <th>交易类型</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${trades.map(trade => `
                                        <tr>
                                            <td>${trade.stock_code || ''}</td>
                                            <td>${trade.stock_name || ''}</td>
                                            <td>${trade.buy_date || ''}</td>
                                            <td>${trade.buy_price || 0}</td>
                                            <td>${trade.sell_date || ''}</td>
                                            <td>${trade.sell_price || 0}</td>
                                            <td class="${(trade.return_rate || 0) >= 0 ? 'text-green-500' : 'text-red-500'}">
                                                ${(trade.return_rate || 0).toFixed(2)}%
                                            </td>
                                            <td>${trade.sell_type || trade.trade_type || 'normal'}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }
    }
}

/**
 * 加载回测历史记录
 */
async function loadBacktestHistory() {
    try {
        console.log('开始加载回测历史...');
        const response = await fetch('/api/trading/backtest/results');
        console.log('API 响应状态:', response.status);
        
        if (!response.ok) {
            throw new Error(`HTTP 错误! 状态: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('API 返回数据:', data);
        
        if (data.success) {
            const results = data.data.results || [];
            console.log('回测结果数量:', results.length);
            displayBacktestHistory(results);
        } else {
            throw new Error(data.message || '加载回测历史失败');
        }
    } catch (error) {
        console.error('加载回测历史失败:', error);
        showHistoryEmptyState('加载回测历史失败: ' + error.message);
    }
}

/**
 * 显示回测历史记录
 * @param {Array} results - 回测结果数组
 */
function displayBacktestHistory(results) {
    const historyBody = document.getElementById('backtest-history-body');
    if (historyBody) {
        if (results.length === 0) {
            historyBody.innerHTML = '<tr><td colspan="9" class="loading">暂无回测历史记录</td></tr>';
        } else {
            historyBody.innerHTML = results.map(result => `
                <tr>
                    <td>${result.strategy_name || ''}</td>
                    <td>${result.start_date || ''}</td>
                    <td>${result.end_date || ''}</td>
                    <td class="${result.total_return >= 0 ? 'text-green-500' : 'text-red-500'}">
                        ${(result.total_return || 0).toFixed(2)}%
                    </td>
                    <td>${(result.win_rate || 0).toFixed(2)}%</td>
                    <td>${(result.max_drawdown || 0).toFixed(2)}%</td>
                    <td>${(result.sharpe_ratio || 0).toFixed(2)}</td>
                    <td>
                        <button class="btn btn-primary btn-sm" onclick="viewBacktestResult(${result.id})">
                            查看
                        </button>
                    </td>
                    <td>
                        <button class="btn btn-success btn-sm" onclick="exportBacktestResult(${result.id})" title="导出Excel">
                            📥 导出
                        </button>
                    </td>
                </tr>
            `).join('');
        }
    }
}

/**
 * 导出回测结果为Excel
 * @param {number} resultId - 回测结果ID
 */
async function exportBacktestResult(resultId) {
    try {
        // 显示加载提示
        showAlert('正在导出回测报告...', 'info');
        
        const response = await fetch(`/api/trading/backtest/results/${resultId}/export`);
        
        if (response.ok) {
            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = '回测报告.xlsx';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="([^"]+)"/);
                if (match && match[1]) {
                    filename = decodeURIComponent(match[1]);
                }
            }
            
            // 下载文件
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            showAlert('导出成功', 'success');
        } else {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.message || '导出失败');
        }
    } catch (error) {
        console.error('导出回测结果失败:', error);
        showAlert('导出失败: ' + error.message, 'error');
    }
}

/**
 * 显示提示信息
 */
function showAlert(message, type = 'info') {
    if (typeof window.showAlert === 'function') {
        window.showAlert(message, type);
        return;
    }
    if (type === 'error') {
        alert('错误: ' + message);
    } else if (type === 'success') {
        alert('成功: ' + message);
    } else {
        console.log(message);
    }
}

/**
 * 查看回测结果
 * @param {number} resultId - 回测结果ID
 */
function viewBacktestResult(resultId) {
    // 显示模态框
    const modal = document.getElementById('backtest-result-modal');
    if (modal) {
        modal.style.display = 'block';
    }
    
    // 加载回测结果到模态框
    loadBacktestResultInModal(resultId);
}

/**
 * 关闭回测结果模态框
 */
function closeBacktestModal() {
    const modal = document.getElementById('backtest-result-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 在模态框中加载回测结果
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestResultInModal(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}`);
        if (!response.ok) {
            throw new Error('加载回测结果失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const result = data.data;
            displayBacktestResultInModal(result);
            
            // 绘制收益曲线
            if (result.equity_curve) {
                const capitalHistory = result.equity_curve.map(item => item.capital);
                const dates = result.equity_curve.map(item => item.date);
                drawEquityChartInModal(capitalHistory, dates);
            }
            
            // 加载交易记录
            loadBacktestTradesInModal(resultId);
        } else {
            throw new Error(data.message || '加载回测结果失败');
        }
    } catch (error) {
        console.error('加载回测结果失败:', error);
        alert('加载回测结果失败: ' + error.message);
        closeBacktestModal();
    }
}

/**
 * 在模态框中显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResultInModal(result) {
    const resultsContainer = document.getElementById('modal-backtest-results-container');
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>回测概览</h3>
                </div>
                <div class="card-body">
                    <!-- 第一行：基本信息 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>策略名称</label>
                            <input type="text" value="${result.strategy_name || ''}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>回测期间</label>
                            <input type="text" value="${result.start_date || ''} 至 ${result.end_date || ''}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 200px;">
                            <label>支撑位置计算方法</label>
                            <input type="text" value="${result.support_level_method || ''}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第二行：资金信息 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>初始资金</label>
                            <input type="text" value="${result.initial_capital || 0}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>最终资金</label>
                            <input type="text" value="${(result.final_capital || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>总收益率</label>
                            <input type="text" value="${(result.total_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>最大回撤</label>
                            <input type="text" value="${(result.max_drawdown || 0).toFixed(2)}%" disabled>
                        </div>
                    </div>
                    
                    <!-- 第三行：交易统计 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>胜率</label>
                            <input type="text" value="${(result.win_rate || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>平均收益率</label>
                            <input type="text" value="${(result.avg_return || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>盈亏比</label>
                            <input type="text" value="${(result.profit_loss_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>总交易次数</label>
                            <input type="text" value="${result.total_trades || 0}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第四行：风险指标 -->
                    <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>夏普比率</label>
                            <input type="text" value="${(result.sharpe_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>索提诺比率</label>
                            <input type="text" value="${(result.sortino_ratio || 0).toFixed(2)}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>波动率</label>
                            <input type="text" value="${(result.volatility || 0).toFixed(2)}%" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>盈利交易次数</label>
                            <input type="text" value="${result.winning_trades || 0}" disabled>
                        </div>
                    </div>
                    
                    <!-- 第五行：其他统计 -->
                    <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>亏损交易次数</label>
                            <input type="text" value="${result.losing_trades || 0}" disabled>
                        </div>
                        <div class="form-group" style="flex: 1; min-width: 150px;">
                            <label>平均持有天数</label>
                            <input type="text" value="${(result.avg_hold_days || 0).toFixed(2)}" disabled>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 收益曲线图表 -->
            <div class="card" style="margin-bottom: 20px;">
                <div class="card-header">
                    <h3>收益曲线</h3>
                </div>
                <div class="card-body">
                    <canvas id="modal-backtest-equity-chart" style="height: 300px;"></canvas>
                </div>
            </div>
        `;
    }
}

/**
 * 在模态框中加载回测交易记录
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTradesInModal(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTradesInModal(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 在模态框中显示回测交易记录
 * @param {Array} trades - 交易记录数组
 */
function displayBacktestTradesInModal(trades) {
    const tradesContainer = document.getElementById('modal-backtest-trades-container');
    if (tradesContainer) {
        if (trades.length === 0) {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <p class="text-center">暂无交易记录</p>
                    </div>
                </div>
            `;
        } else {
            tradesContainer.innerHTML = `
                <div class="card">
                    <div class="card-header">
                        <h3>交易记录</h3>
                    </div>
                    <div class="card-body">
                        <div class="overflow-x-auto">
                            <table class="table">
                                <thead>
                                    <tr>
                                        <th>股票代码</th>
                                        <th>股票名称</th>
                                        <th>买入日期</th>
                                        <th>买入价格</th>
                                        <th>卖出日期</th>
                                        <th>卖出价格</th>
                                        <th>收益率</th>
                                        <th>交易类型</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${trades.map(trade => `
                                        <tr>
                                            <td>${trade.stock_code}</td>
                                            <td>${trade.stock_name}</td>
                                            <td>${trade.buy_date}</td>
                                            <td>${trade.buy_price}</td>
                                            <td>${trade.sell_date}</td>
                                            <td>${trade.sell_price}</td>
                                            <td class="${trade.return_rate >= 0 ? 'text-green-500' : 'text-red-500'}">
                                                ${trade.return_rate.toFixed(2)}%
                                            </td>
                                            <td>${trade.sell_type}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `;
        }
    }
}

/**
 * 显示结果页面空状态
 * @param {string} message - 提示信息
 */
function showResultsEmptyState(message) {
    const resultsContainer = document.getElementById('backtest-results-container');
    const tradesContainer = document.getElementById('backtest-trades-container');
    
    if (resultsContainer) {
        resultsContainer.innerHTML = `
            <div class="card">
                <div class="card-header">
                    <h3>回测结果</h3>
                </div>
                <div class="card-body">
                    <p class="text-center">${message}</p>
                </div>
            </div>
        `;
    }
    
    if (tradesContainer) {
        tradesContainer.innerHTML = '';
    }
}

/**
 * 显示历史页面空状态
 * @param {string} message - 提示信息
 */
function showHistoryEmptyState(message) {
    const historyBody = document.getElementById('backtest-history-body');
    if (historyBody) {
        historyBody.innerHTML = `<tr><td colspan="8" class="loading">${message}</td></tr>`;
    }
}

/**
 * 搜索回测历史
 */
export async function searchBacktestHistory() {
    try {
        const strategyFilter = document.getElementById('history-strategy-filter');
        const startDateInput = document.getElementById('history-start-date');
        const endDateInput = document.getElementById('history-end-date');
        
        const params = new URLSearchParams();
        if (strategyFilter?.value) params.append('strategy', strategyFilter.value);
        if (startDateInput?.value) params.append('start_date', startDateInput.value);
        if (endDateInput?.value) params.append('end_date', endDateInput.value);
        
        const queryString = params.toString();
        const url = `/api/trading/backtest/results${queryString ? `?${queryString}` : ''}`;
        
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('搜索回测历史失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const results = data.data.results;
            displayBacktestHistory(results);
        } else {
            throw new Error(data.message || '搜索回测历史失败');
        }
    } catch (error) {
        console.error('搜索回测历史失败:', error);
        showHistoryEmptyState('搜索回测历史失败: ' + error.message);
    }
}

/**
 * 在策略回测页面显示回测结果
 * @param {Object} result - 回测结果数据
 */
function displayBacktestResultOnConfigPage(result) {
    // 显示结果容器
    const resultContainer = document.getElementById('backtest-result-container');
    if (resultContainer) {
        resultContainer.style.display = 'block';
    }
    
    // 更新绩效指标卡片
    const totalReturnEl = document.getElementById('backtest-total-return');
    const winRateEl = document.getElementById('backtest-win-rate');
    const maxDrawdownEl = document.getElementById('backtest-max-drawdown');
    const sharpeRatioEl = document.getElementById('backtest-sharpe-ratio');
    
    if (totalReturnEl) totalReturnEl.textContent = `${(result.total_return || 0).toFixed(2)}%`;
    if (winRateEl) winRateEl.textContent = `${(result.win_rate || 0).toFixed(2)}%`;
    if (maxDrawdownEl) maxDrawdownEl.textContent = `${(result.max_drawdown || 0).toFixed(2)}%`;
    if (sharpeRatioEl) sharpeRatioEl.textContent = (result.sharpe_ratio || 0).toFixed(2);
    
    // 绘制收益曲线
    // 注意：result 中没有 capital_history 和 dates，需要从 equity_curve 中提取
    if (result.equity_curve && result.equity_curve.length > 0) {
        const capitalHistory = result.equity_curve.map(item => item.capital);
        const dates = result.equity_curve.map(item => item.date);
        drawEquityChart(capitalHistory, dates);
    } else if (result.capital_history && result.capital_history.length > 0) {
        // 如果没有 equity_curve，尝试使用 capital_history 和 dates（备用方案）
        drawEquityChart(result.capital_history, result.dates || []);
    } else {
        // 如果没有任何收益曲线数据，显示提示信息
        console.warn('没有收益曲线数据');
        const ctx = document.getElementById('backtest-equity-chart');
        if (ctx && ctx.parentElement) {
            ctx.parentElement.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无收益曲线数据</div>';
        }
    }
}

/**
 * 绘制收益曲线
 * @param {Array} capitalHistory - 资金历史
 * @param {Array} dates - 日期列表
 */
function drawEquityChart(capitalHistory, dates) {
    // 检查数据有效性
    if (!capitalHistory || capitalHistory.length === 0 || !dates || dates.length === 0) {
        console.warn('收益曲线数据为空，无法绘制图表');
        const ctx = document.getElementById('backtest-equity-chart');
        if (ctx) {
            const parent = ctx.parentElement;
            if (parent) {
                parent.innerHTML = '<div style="text-align: center; padding: 40px; color: #6b7280;">暂无收益曲线数据</div>';
            }
        }
        return;
    }
    
    const ctx = document.getElementById('backtest-equity-chart');
    if (!ctx) {
        console.error('找不到图表容器元素');
        return;
    }
    
    // 销毁旧图表
    if (window.equityChart) {
        window.equityChart.destroy();
    }
    
    // 准备数据
    const labels = dates.map(date => {
        if (date instanceof Date) {
            return date.toISOString().split('T')[0];
        }
        return date;
    });
    
    // 计算收益率
    const initialCapital = capitalHistory[0] || 1000000;
    const returns = capitalHistory.map(capital => {
        return ((capital - initialCapital) / initialCapital) * 100;
    });
    
    // 创建新图表
    try {
        window.equityChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: '收益率 (%)',
                    data: returns,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: '收益率 (%)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: '日期'
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('绘制收益曲线失败:', error);
    }
}

/**
 * 在模态框中绘制收益曲线
 * @param {Array} capitalHistory - 资金历史
 * @param {Array} dates - 日期列表
 */
function drawEquityChartInModal(capitalHistory, dates) {
    const ctx = document.getElementById('modal-backtest-equity-chart');
    if (!ctx) {
        // 如果模态框中没有图表元素，添加一个
        const modalContent = document.getElementById('modal-backtest-results-container');
        if (modalContent) {
            modalContent.innerHTML += `
                <div class="card" style="margin-bottom: 20px;">
                    <div class="card-header">
                        <h3>收益曲线</h3>
                    </div>
                    <div class="card-body">
                        <canvas id="modal-backtest-equity-chart" style="height: 300px;"></canvas>
                    </div>
                </div>
            `;
        }
    }
    
    const chartCtx = document.getElementById('modal-backtest-equity-chart').getContext('2d');
    
    // 销毁旧图表
    if (window.modalEquityChart) {
        window.modalEquityChart.destroy();
    }
    
    // 准备数据
    const labels = dates.map(date => {
        if (date instanceof Date) {
            return date.toISOString().split('T')[0];
        }
        return date;
    });
    
    // 计算收益率
    const initialCapital = capitalHistory[0] || 1000000;
    const returns = capitalHistory.map(capital => {
        return ((capital - initialCapital) / initialCapital) * 100;
    });
    
    // 创建新图表
    window.modalEquityChart = new Chart(chartCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '收益率 (%)',
                data: returns,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: '收益率 (%)'
                    }
                },
                x: {
                    title: {
                        display: true,
                        text: '日期'
                    }
                }
            }
        }
    });
}

/**
 * 加载回测交易记录（在策略回测页面）
 * @param {number} resultId - 回测结果ID
 */
async function loadBacktestTradesOnConfigPage(resultId) {
    try {
        const response = await fetch(`/api/trading/backtest/results/${resultId}/trades`);
        if (!response.ok) {
            throw new Error('加载交易记录失败');
        }
        
        const data = await response.json();
        if (data.success) {
            const trades = data.data.trades;
            displayBacktestTradesOnConfigPage(trades);
        } else {
            throw new Error(data.message || '加载交易记录失败');
        }
    } catch (error) {
        console.error('加载交易记录失败:', error);
        alert('加载交易记录失败: ' + error.message);
    }
}

/**
 * 在策略回测页面显示交易记录
 * @param {Array} trades - 交易记录数组
 */
function displayBacktestTradesOnConfigPage(trades) {
    const tradesBody = document.getElementById('backtest-trades-body');
    if (!tradesBody) {
        console.error('找不到交易记录表格容器');
        return;
    }
    
    // 检查trades是否为有效的数组
    if (!Array.isArray(trades)) {
        console.warn('交易记录不是数组:', trades);
        tradesBody.innerHTML = '<tr><td colspan="6" class="text-center">交易记录格式错误</td></tr>';
        return;
    }
    
    if (trades.length === 0) {
        tradesBody.innerHTML = '<tr><td colspan="6" class="text-center">暂无交易记录</td></tr>';
    } else {
        try {
            tradesBody.innerHTML = trades.map(trade => {
                // 安全地获取交易数据
                const stockCode = trade.stock_code || '-';
                const stockName = trade.stock_name || '-';
                const buyDate = trade.buy_date || '-';
                const sellDate = trade.sell_date || '-';
                const holdDays = trade.hold_days || '-';
                const returnRate = trade.return_rate;
                
                // 确定收益率的颜色
                let returnRateClass = '';
                let returnRateText = '-';
                if (returnRate !== null && returnRate !== undefined) {
                    returnRateClass = returnRate >= 0 ? 'text-green-500' : 'text-red-500';
                    returnRateText = returnRate.toFixed(2) + '%';
                }
                
                return `
                    <tr>
                        <td>${stockCode}</td>
                        <td>${stockName}</td>
                        <td>${buyDate}</td>
                        <td>${sellDate}</td>
                        <td>${holdDays}</td>
                        <td class="${returnRateClass}">${returnRateText}</td>
                    </tr>
                `;
            }).join('');
        } catch (error) {
            console.error('显示交易记录失败:', error);
            tradesBody.innerHTML = '<tr><td colspan="6" class="text-center">显示交易记录失败</td></tr>';
        }
    }
}

// 暴露全局函数
window.viewBacktestResult = viewBacktestResult;
window.searchBacktestHistory = searchBacktestHistory;
window.closeBacktestModal = closeBacktestModal;
window.exportBacktestResult = exportBacktestResult;
