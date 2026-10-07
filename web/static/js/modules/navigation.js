/**
 * 页面导航相关功能模块
 */

// ★★【2026-10-04 用户要求 ✓】**全站前端统一版本号** ✗→✓ ★★
//   本模块是**懒加载的唯一出口** ✗✓（所有页面模块都由它 `import()` 拉起 ✓）
//   ⇒ 此前必须手写 `?v=20260928` ✗，改了别的模块还要记得回来递增 ✗（踩过坑 ✓）。
//   现在 ✓：**从自身 URL 取出 `?v=NN`** ✓（源头 = `index.html` 的 `app.js?v=NN` ✓，
//   由 `app.js` 传播到本文件 ✓）⇒ 再往下传 ✓ ⇒ **一处 bump 全链失效** ✓✓。
//   ⚠️ 新增 import 一律写 `imp('./x.js')` ✓（**不要**自带 `?` ✗）。
const V = new URL(import.meta.url).search;
const imp = (p) => import(p + V);

/**
 * 设置导航事件监听
 */
export function setupNavigation() {
    // 页面切换
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            switchPage(page);
        });
    });
}

/**
 * 页面切换函数
 * @param {string} page - 页面名称
 */
export function switchPage(page) {
    console.log('切换页面到:', page);
    
    // 更新导航
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });
    
    // 更新页面标题 - 完整的标题映射，包含所有导航菜单项
    const titles = {
        'dashboard': '市场速览',
        'stocks': '基础数据',
        'data-init': '初始化数据',
        'data-update': '数据更新',
        'selection': '选股结果',
        'history': '历史选股',
        'trading': '账户总览',
        'positions': '持仓明细',
        'transactions': '交易历史',
        'strategies': '策略配置',
        'analysis': '个股图谱',
        'stock-ranking': '选股排名',
        'ranking-track': '排名跟踪',
        'backtest-params': '回测配置',
        'backtest-config': '策略回测',
        'backtest-results': '回测结果',
        'backtest-history': '回测历史',
        'regime-backtest': '自适应回测',
        'khunter': '狩猎场',
        'khunter-track': '狩猎跟踪',
        'favorites': '收藏夹',
        'strategy-runner': '策略执行器'
    };
    
    // 获取页面标题，如果不存在则使用默认标题
    const pageTitle = titles[page] || '系统概览';
    document.getElementById('page-title').textContent = pageTitle;
    
    // 显示对应页面
    document.querySelectorAll('.page').forEach(p => {
        p.classList.toggle('active', p.id === page + '-page');
    });
    
    console.log('页面切换完成，当前页面:', page);
    
    // 加载页面数据
    if (page === 'dashboard') {
        imp('./stocks.js').then(module => module.loadStats());
    } else if (page === 'stocks') {
        imp('./stocks.js').then(module => module.loadStocks());
    } else if (page === 'data-init') {
        // 初始化数据页面 - 重置表单
        console.log('调用 resetInitForm()');
        resetInitForm();
    } else if (page === 'data-update') {
        // 数据更新页面 - 初始化
        initDataUpdatePage();
    } else if (page === 'history') {
        imp('./stocks.js').then(module => module.loadHistoryStrategyOptions());
        // 不再自动查询，等待用户点击查询按钮
        imp('./history.js').then(module => module.showHistoryEmptyState('请点击"查询"按钮加载数据'));
    } else if (page === 'trading') {
        // 初始化交易模块 - 账户总览
        initTrading(page);
    } else if (page === 'positions') {
        // 初始化交易模块 - 持仓明细
        initTrading(page);
    } else if (page === 'transactions') {
        // 初始化交易模块 - 交易历史
        initTrading(page);
    } else if (page === 'strategies') {
        imp('./strategies.js').then(module => module.loadStrategies());
    } else if (page === 'analysis') {
        // 个股图谱页面 - 重置状态
        imp('./analysis.js').then(module => module.resetScorePageState());
    } else if (page === 'stock-ranking') {
        // 选股排名页面 - 初始化
        imp('./ranking.js').then(module => module.initStockRankingPage());
    } else if (page === 'ranking-track') {
        // 排名跟踪页面 - 初始化
        imp('./ranking.js').then(module => module.initRankingTrackPage());
    } else if (page === 'backtest-params') {
        // 回测参数配置页面 - 初始化
        imp('./backtest.js').then(module => module.initBacktestParamsPage());
    } else if (page === 'backtest-config') {
        // 策略回测页面 - 初始化
        imp('./backtest.js').then(module => module.initBacktestConfigPage());
    } else if (page === 'backtest-history') {
        // 回测历史页面 - 初始化
        imp('./backtest.js').then(module => module.initBacktestHistoryPage());
    } else if (page === 'regime-backtest') {
        // 自适应回测页面 - 初始化
        // ★【2026-10-04 统一版本号 ✓】不再手写 `?v=` ✗ —— 由 `imp()` 自动带上 ✓
        //   （旧事故 ✓：此处曾写死 `?v=20260928` ✓，改了 `regime-backtest.js` 忘递增 ⇒
        //    浏览器仍用旧缓存 ✗ ⇒「res is not defined」修了也白修 ✗✓）
        imp('./regime-backtest.js').then(module => module.initRegimeBacktestPage());
    } else if (page === 'khunter') {
        // 狩猎场页面 - 初始化
        imp('./khunter.js').then(module => module.initKHunterPage());
    } else if (page === 'khunter-track') {
        // 狩猎跟踪页面 - 初始化
        imp('./khunter.js').then(module => {
            module.initKHunterTrackPage();
            module.setupKHunterTrackingEvents();
        });
    } else if (page === 'favorites') {
        // 收藏夹页面 - 初始化
        imp('./favorites.js').then(module => module.loadFavorites());
    } else if (page === 'strategy-runner') {
        // 策略执行器页面 - 初始化
        imp('./strategy-runner.js').then(module => {
            module.default.initStrategyRunnerModule().catch(err => {
                console.error('初始化策略执行器模块失败:', err);
            });
        }).catch(err => {
            console.error('加载策略执行器模块失败:', err);
        });
    }
}

/**
 * 重置初始化表单
 */
function resetInitForm() {
    // 这里可以添加重置初始化表单的逻辑
    console.log('重置初始化表单');
}

/**
 * 初始化数据更新页面
 */
function initDataUpdatePage() {
    // 这里可以添加初始化数据更新页面的逻辑
    console.log('初始化数据更新页面');
}

/**
 * 初始化交易模块
 */
function initTrading(page) {
    // 调用trading.js中的initTrading函数
    if (typeof window.initTrading === 'function') {
        window.initTrading(page);
    }
}
