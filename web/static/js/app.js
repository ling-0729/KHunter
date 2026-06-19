/**
 * A股量化选股系统 - 主入口文件
 */

// 全局状态
let currentPage = 'dashboard';
let chartInstance = null;
// 缓存最近一次选股结果，用于手动保存
let lastSelectionResults = null;
let lastSelectionTime = null;

// 模块变量
let modules = {};

// 检查策略配置文件是否存在
async function checkStrategyConfig() {
    try {
        const response = await fetch('/api/strategy/has-config');
        const result = await response.json();
        
        if (result.success) {
            const hasConfig = result.has_config;
            
            // 如果没有配置文件，隐藏策略执行器菜单和页面
            if (!hasConfig) {
                const strategyRunnerMenu = document.querySelector('.nav-item[data-page="strategy-runner"]');
                const strategyRunnerPage = document.getElementById('strategy-runner-page');
                
                if (strategyRunnerMenu) {
                    strategyRunnerMenu.style.display = 'none';
                    console.log('未检测到配置文件，已隐藏策略执行器菜单');
                }
                if (strategyRunnerPage) {
                    strategyRunnerPage.style.display = 'none';
                }
            }
            
            return hasConfig;
        }
    } catch (error) {
        console.error('检查策略配置文件失败:', error);
    }
    return false;
}

// 动态加载模块
async function loadModules() {
    try {
        // 加载各个模块
        const websocketModule = await import('./modules/websocket.js');
        const navigationModule = await import('./modules/navigation.js');
        const stocksModule = await import('./modules/stocks.js');
        const selectionModule = await import('./modules/selection.js');
        const analysisModule = await import('./modules/analysis.js');
        const strategiesModule = await import('./modules/strategies.js');
        const historyModule = await import('./modules/history.js');
        const rankingModule = await import('./modules/ranking.js');
        const utilsModule = await import('./modules/utils.js');
        const backtestModule = await import('./modules/backtest.js');
        const backtestBatchModule = await import('./modules/backtest-batch.js');
        const backtestExecutorModule = await import('./modules/backtest-executor.js');
        const marketTempModule = await import('./modules/market_temperature.js');
        const moneyFlowModule = await import('./modules/money_flow.js');
        const strategyRunnerModule = await import('./modules/strategy-runner.js');
        const riskModule = await import('./modules/risk.js');
        
        // 存储模块
        modules = {
            websocket: websocketModule,
            navigation: navigationModule,
            stocks: stocksModule,
            selection: selectionModule,
            analysis: analysisModule,
            strategies: strategiesModule,
            history: historyModule,
            ranking: rankingModule,
            utils: utilsModule,
            backtest: backtestModule,
            backtestBatch: backtestBatchModule,
            backtestExecutor: backtestExecutorModule,
            marketTemp: marketTempModule,
            moneyFlow: moneyFlowModule,
            strategyRunner: strategyRunnerModule,
            risk: riskModule
        };
        
        // 初始化
        await initializeApp();
    } catch (error) {
        console.error('Failed to load modules:', error);
        alert('加载模块失败，请刷新页面重试');
    }
}

// 初始化应用
async function initializeApp() {
    // 检查配置文件状态，决定是否显示策略执行器菜单
    await checkStrategyConfig();
    
    // 初始化WebSocket连接
    modules.websocket.initWebSocket();
    
    // 初始化导航
    modules.navigation.setupNavigation();
    
    // 初始化页面标题 - 确保页面加载时标题正确显示
    modules.navigation.switchPage(currentPage);
    
    modules.stocks.loadStats();
    modules.stocks.loadMyGoldenStocks();
    modules.stocks.loadHotIndustries();
    modules.stocks.loadHotAreas();
    modules.analysis.setupStockAnalysis();
    modules.ranking.setupRankingEvents();
    
    // 初始化批量回测模块
    await modules.backtestBatch.initBacktestBatchModule();
    
    // 初始化资金流向选股页面
    modules.moneyFlow.initMoneyFlowPage();
    
    // 初始化风控模块
    modules.risk.initRiskModule();
    
    // 注：策略执行器模块在 navigation.js 中懒加载（用户切换到策略运行器页面时才初始化）
    
    // 暴露全局函数（供HTML调用）
    window.switchPage = modules.navigation.switchPage;
    window.runSelection = modules.selection.runSelection;
    window.confirmStrategySelection = modules.selection.confirmStrategySelection;
    window.closeStrategyModal = modules.selection.closeStrategyModal;
    window.selectAllStrategies = modules.selection.selectAllStrategies;
    window.deselectAllStrategies = modules.selection.deselectAllStrategies;
    window.saveSelectionResults = modules.selection.saveSelectionResults;
    window.viewStockDetail = modules.stocks.viewStockDetail;
    window.closeModal = modules.stocks.closeModal;
    window.triggerUpdate = triggerUpdate;
    window.loadStrategies = modules.strategies.loadStrategies;
    window.viewStrategyDetail = modules.strategies.viewStrategyDetail;
    window.saveStrategyParams = modules.strategies.saveStrategyParams;
    window.resetStrategyParams = modules.strategies.resetStrategyParams;
    window.backToStrategyList = modules.strategies.backToStrategyList;
    window.searchSelectionHistory = modules.history.searchSelectionHistory;
    window.goToHistoryPage = modules.history.goToHistoryPage;
    window.resetHistoryFilters = modules.history.resetHistoryFilters;
    window.generateRanking = modules.ranking.generateRanking;
    window.trackRanking = modules.ranking.trackRanking;
    window.showScoreDetail = modules.analysis.showScoreDetail;
    window.closeScoreDetailModal = modules.analysis.closeScoreDetailModal;
    window.showIndustryStocks = modules.stocks.showIndustryStocks;
    window.showAreaStocks = modules.stocks.showAreaStocks;
    
    // 暴露批量回测相关函数（供HTML调用）
    window.removeBacktestTask = modules.backtestBatch.removeBacktestTask;
    window.searchBacktestHistory = modules.backtest.searchBacktestHistory;
    window.viewBacktestResult = modules.backtest.viewBacktestResult;
    window.exportBacktestResult = modules.backtest.exportBacktestResult;
    window.deleteBacktestResult = modules.backtest.deleteBacktestResult;
    window.closeBacktestModal = modules.backtest.closeBacktestModal;
    
    // 绑定按钮事件
    const runSelectionBtn = document.getElementById('run-selection-btn');
    if (runSelectionBtn) {
        runSelectionBtn.addEventListener('click', modules.selection.runSelection);
    }
    
    const saveSelectionBtn = document.getElementById('save-selection-btn');
    if (saveSelectionBtn) {
        saveSelectionBtn.addEventListener('click', modules.selection.saveSelectionResults);
    }
    
    const confirmStrategyBtn = document.getElementById('confirm-strategy-btn');
    if (confirmStrategyBtn) {
        confirmStrategyBtn.addEventListener('click', modules.selection.confirmStrategySelection);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', loadModules);

// 触发数据更新
async function triggerUpdate() {
    const progressCard = document.getElementById('update-progress-card');
    
    // 确认更新
    if (!confirm('确定要更新数据吗？这可能需要几分钟时间。')) {
        return;
    }
    
    progressCard.style.display = 'block';
    
    try {
        // 发起更新请求
        const response = await fetch('/api/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ max_stocks: null })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 使用WebSocket接收实时进度，无需轮询
            console.log('Update started, waiting for WebSocket updates...');
            // 保留轮询作为WebSocket的备用方案
            if (modules.websocket) {
                modules.websocket.checkUpdateStatusBackup(progressCard);
            }
        } else {
            alert('Update failed: ' + result.error);
            progressCard.style.display = 'none';
        }
    } catch (error) {
        alert('Update failed: ' + error.message);
        progressCard.style.display = 'none';
    }
}
