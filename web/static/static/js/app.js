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
            backtestExecutor: backtestExecutorModule
        };
        
        // 初始化
        initializeApp();
    } catch (error) {
        console.error('Failed to load modules:', error);
        alert('加载模块失败，请刷新页面重试');
    }
}

// 初始化应用
function initializeApp() {
    // 初始化WebSocket连接
    modules.websocket.initWebSocket();
    
    // 初始化导航
    modules.navigation.setupNavigation();
    
    // 初始化页面标题 - 确保页面加载时标题正确显示
    modules.navigation.switchPage(currentPage);
    
    modules.stocks.loadStats();
    modules.analysis.setupStockAnalysis();
    modules.ranking.setupRankingEvents();
    
    // 初始化批量回测模块
    modules.backtestBatch.initBacktestBatchModule();
    
    // // 初始化执行管理器（需要在批量回测模块之后初始化）
    // try {
    //     // 从 backtestBatch 模块获取任务管理器和UI管理器实例
    //     const { backtestTaskManager, backtestUIManager } = modules.backtestBatch;
    //     modules.backtestExecutor.initBacktestExecutor(backtestTaskManager, backtestUIManager);
    // } catch (error) {
    //     console.warn('执行管理器初始化失败:', error);
    // }
    
    // 加载首页数据
    modules.stocks.loadMyGoldenStocks();
    modules.stocks.loadHotIndustries();
    modules.stocks.loadHotAreas();
    
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
