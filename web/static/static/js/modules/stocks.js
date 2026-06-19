/**
 * 股票相关功能模块
 */

/**
 * 加载统计信息
 */
export async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const result = await response.json();
        
        if (result.success) {
            document.getElementById('stat-stocks').textContent = result.data.total_stocks;
            document.getElementById('stat-date').textContent = result.data.latest_date;
            document.getElementById('stat-strategies').textContent = result.data.strategies;
        }
    } catch (error) {
        console.error('加载统计信息失败:', error);
    }
}

/**
 * 加载我的金股数据
 */
export async function loadMyGoldenStocks() {
    try {
        const response = await fetch('/api/dashboard/my-golden-stocks');
        const result = await response.json();
        
        if (result.success) {
            const container = document.getElementById('my-golden-stocks-content');
            if (result.stocks.length === 0) {
                container.innerHTML = '<p class="text-muted">暂无金股数据</p>';
                return;
            }
            
            let html = `
                <div class="table-responsive">
                    <table class="table table-striped">
                        <thead>
                            <tr>
                                <th>排名</th>
                                <th>股票代码</th>
                                <th>股票名称</th>
                                <th>评分</th>
                                <th>行业</th>
                                <th>板块</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            result.stocks.forEach((stock, index) => {
                html += `
                    <tr>
                        <td>${index + 1}</td>
                        <td><a href="javascript:void(0)" onclick="viewStockDetail('${stock.stock_code}')" class="stock-link">${stock.stock_code}</a></td>
                        <td>${stock.stock_name}</td>
                        <td><a href="javascript:void(0)" onclick="showScoreDetail('${stock.stock_code}', '${result.date}')" class="score-link">${(stock.total_score || 0).toFixed(2)}</a></td>
                        <td>${stock.industry || '-'}</td>
                        <td>${stock.area || '-'}</td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <p class="text-muted" style="margin-top: 10px; font-size: 12px;">数据日期: ${result.date}</p>
            `;
            
            container.innerHTML = html;
        } else {
            document.getElementById('my-golden-stocks-content').innerHTML = `<p class="text-danger">加载失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('加载我的金股失败:', error);
        document.getElementById('my-golden-stocks-content').innerHTML = `<p class="text-danger">加载失败: ${error.message}</p>`;
    }
}

/**
 * 加载最热行业数据
 */
export async function loadHotIndustries() {
    try {
        const response = await fetch('/api/dashboard/hot-industries');
        const result = await response.json();
        
        if (result.success) {
            const container = document.getElementById('hot-industries-content');
            if (result.industries.length === 0) {
                container.innerHTML = '<p class="text-muted">暂无行业数据</p>';
                return;
            }
            
            let html = `
                <div class="table-responsive">
                    <table class="table table-striped">
                        <thead>
                            <tr>
                                <th>排名</th>
                                <th>行业</th>
                                <th>股票数量</th>
                                <th>占比</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            // 只显示前5个行业
            const top5Industries = result.industries.slice(0, 5);
            top5Industries.forEach((industry, index) => {
                html += `
                    <tr>
                        <td>${index + 1}</td>
                        <td>${industry.industry}</td>
                        <td><a href="javascript:void(0)" onclick="showIndustryStocks('${industry.industry}', ${industry.count})" class="stock-link">${industry.count}</a></td>
                        <td>${industry.percentage}%</td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <p class="text-muted" style="margin-top: 10px; font-size: 12px;">数据日期: ${result.date}</p>
            `;
            
            container.innerHTML = html;
        } else {
            document.getElementById('hot-industries-content').innerHTML = `<p class="text-danger">加载失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('加载最热行业失败:', error);
        document.getElementById('hot-industries-content').innerHTML = `<p class="text-danger">加载失败: ${error.message}</p>`;
    }
}

/**
 * 加载最热板块数据
 */
export async function loadHotAreas() {
    try {
        const response = await fetch('/api/dashboard/hot-areas');
        const result = await response.json();
        
        if (result.success) {
            const container = document.getElementById('hot-areas-content');
            if (result.areas.length === 0) {
                container.innerHTML = '<p class="text-muted">暂无板块数据</p>';
                return;
            }
            
            let html = `
                <div class="table-responsive">
                    <table class="table table-striped">
                        <thead>
                            <tr>
                                <th>排名</th>
                                <th>板块</th>
                                <th>股票数量</th>
                                <th>占比</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            // 只显示前5个板块
            const top5Areas = result.areas.slice(0, 5);
            top5Areas.forEach((area, index) => {
                html += `
                    <tr>
                        <td>${index + 1}</td>
                        <td>${area.area}</td>
                        <td><a href="javascript:void(0)" onclick="showAreaStocks('${area.area}', ${area.count})" class="stock-link">${area.count}</a></td>
                        <td>${area.percentage}%</td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <p class="text-muted" style="margin-top: 10px; font-size: 12px;">数据日期: ${result.date}</p>
            `;
            
            container.innerHTML = html;
        } else {
            document.getElementById('hot-areas-content').innerHTML = `<p class="text-danger">加载失败: ${result.error}</p>`;
        }
    } catch (error) {
        console.error('加载最热板块失败:', error);
        document.getElementById('hot-areas-content').innerHTML = `<p class="text-danger">加载失败: ${error.message}</p>`;
    }
}

/**
 * 加载股票列表 - 支持分页获取所有股票
 */
export async function loadStocks() {
    const tbody = document.getElementById('stocks-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">正在加载股票列表...</td></tr>';
    
    try {
        let allStocks = [];
        let page = 1;
        let totalPages = 1;
        
        // 分页获取所有股票
        do {
            const response = await fetch(`/api/stocks?page=${page}&per_page=500`);
            const result = await response.json();
            
            if (result.success) {
                allStocks = allStocks.concat(result.data);
                totalPages = result.total_pages;
                tbody.innerHTML = `<tr><td colspan="7" class="loading">已加载 ${allStocks.length} / ${result.total} 只股票...</td></tr>`;
                page++;
            } else {
                break;
            }
        } while (page <= totalPages);
        
        renderStocks(allStocks);
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="7" class="loading">加载失败: ${error.message}</td></tr>`;
    }
}

/**
 * 渲染股票列表
 * @param {Array} stocks - 股票列表数据
 */
export function renderStocks(stocks) {
    const tbody = document.getElementById('stocks-tbody');
    
    if (stocks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">暂无数据</td></tr>';
        return;
    }
    
    tbody.innerHTML = stocks.map(stock => `
        <tr>
            <td><strong>${stock.code}</strong></td>
            <td>${stock.name}</td>
            <td>¥${stock.latest_price}</td>
            <td>${stock.latest_date}</td>
            <td>${stock.market_cap}</td>
            <td>${stock.data_count}</td>
            <td>
                <button class="btn btn-secondary" onclick="viewStockDetail('${stock.code}')">
                    查看
                </button>
            </td>
        </tr>
    `).join('');
    
    // 搜索功能
    document.getElementById('stock-search').addEventListener('input', (e) => {
        const keyword = e.target.value.toLowerCase();
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(keyword) ? '' : 'none';
        });
    });
}

/**
 * 查看股票详情
 * @param {string} code - 股票代码
 */
export async function viewStockDetail(code) {
    try {
        const response = await fetch(`/api/stock/${code}`);
        const result = await response.json();
        
        if (result.success) {
            showStockModal(code, result.data);
        } else {
            alert('加载股票详情失败: ' + result.error);
        }
    } catch (error) {
        alert('加载股票详情失败: ' + error.message);
    }
}

/**
 * 显示股票详情弹窗
 * @param {string} code - 股票代码
 * @param {Object} data - 股票数据
 */
export function showStockModal(code, data) {
    const modal = document.getElementById('stock-modal');
    document.getElementById('modal-title').textContent = `股票详情: ${code}`;
    
    // 显示K线图表容器
    const chartContainer = document.getElementById('stock-chart-container');
    chartContainer.style.display = 'block';
    
    // 清空股票信息区域，只显示K线图表
    document.getElementById('stock-info').innerHTML = '';
    
    // 先显示模态框，让容器获得正确的尺寸
    modal.classList.add('active');
    
    // 使用requestAnimationFrame确保DOM已更新，容器有正确的宽度
    requestAnimationFrame(() => {
        // 初始化K线图表
        // 注意：使用stock-chart-container而不是stock-chart（canvas元素）
        initKlineChart('stock-chart-container', data);
    });
}

/**
 * 关闭弹窗
 */
export function closeModal() {
    document.getElementById('stock-modal').classList.remove('active');
}

/**
 * 加载策略列表到历史记录下拉框
 */
export async function loadHistoryStrategyOptions() {
    const strategySelect = document.getElementById('history-strategy-filter');
    if (!strategySelect) return;
    
    try {
        const response = await fetch('/api/strategies');
        const data = await response.json();
        
        if (data.success && data.data) {
            // 保留第一个选项（全部策略）
            strategySelect.innerHTML = '<option value="">全部策略</option>';
            
            data.data.forEach(strategy => {
                const option = document.createElement('option');
                // 使用display_name作为value，因为数据库中存储的是中文名称
                option.value = strategy.display_name || strategy.name;
                option.textContent = strategy.display_name || strategy.name;
                // 保存英文名称用于其他用途
                option.dataset.name = strategy.name;
                strategySelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('加载策略列表失败:', error);
    }
}

/**
 * 显示行业股票列表
 * @param {string} industry - 行业名称
 * @param {number} limit - 显示数量
 */
export async function showIndustryStocks(industry, limit = 50) {
    try {
        const response = await fetch(`/api/dashboard/industry-stocks?industry=${encodeURIComponent(industry)}&limit=${limit}`);
        const result = await response.json();
        
        if (result.success) {
            showStocksModal(`${industry}行业股票列表`, result.stocks, result.date || '');
        } else {
            alert('加载行业股票失败: ' + result.error);
        }
    } catch (error) {
        alert('加载行业股票失败: ' + error.message);
    }
}

/**
 * 显示板块股票列表
 * @param {string} area - 板块名称
 * @param {number} limit - 显示数量
 */
export async function showAreaStocks(area, limit = 50) {
    try {
        const response = await fetch(`/api/dashboard/area-stocks?area=${encodeURIComponent(area)}&limit=${limit}`);
        const result = await response.json();
        
        if (result.success) {
            showStocksModal(`${area}板块股票列表`, result.stocks, result.date || '');
        } else {
            alert('加载板块股票失败: ' + result.error);
        }
    } catch (error) {
        alert('加载板块股票失败: ' + error.message);
    }
}

/**
 * 显示股票列表模态框
 * @param {string} title - 模态框标题
 * @param {Array} stocks - 股票列表数据
 * @param {string} date - 评分日期
 */
export function showStocksModal(title, stocks, date) {
    const modal = document.getElementById('stock-modal');
    document.getElementById('modal-title').textContent = title;
    
    // 隐藏K线图表容器，只显示股票列表
    const chartContainer = document.getElementById('stock-chart-container');
    chartContainer.style.display = 'none';
    
    // 清空股票信息区域
    const stockInfo = document.getElementById('stock-info');
    stockInfo.innerHTML = '';
    
    if (stocks.length === 0) {
        stockInfo.innerHTML = '<p class="text-muted">暂无股票数据</p>';
        modal.classList.add('active');
        return;
    }
    
    // 构建表格
    let html = `
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>评分</th>
                        <th>行业</th>
                        <th>板块</th>
                        <th>选入价</th>
                        <th>当前价</th>
                        <th>收益率</th>
                        <th>最高价格</th>
                        <th>最高收益</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    stocks.forEach((item, index) => {
        // 防御性代码，处理可能的undefined值
        const score = item.score || 0;
        const selectionPrice = item.selection_price || 0;
        const currentPrice = item.current_price || 0;
        const currentReturn = item.current_yield || 0;
        const highestPrice = item.highest_price || 0;
        const highestReturn = item.highest_yield || 0;
        
        html += `
            <tr>
                <td>${index + 1}</td>
                <td><a href="javascript:void(0)" onclick="viewStockDetail('${item.stock_code}')" class="stock-link">${item.stock_code}</a></td>
                <td>${item.stock_name}</td>
                <td><a href="javascript:void(0)" onclick="showScoreDetail('${item.stock_code}', '${date}')" class="score-link">${score.toFixed(2)}</a></td>
                <td>${item.industry || '-'}</td>
                <td>${item.sector || '-'}</td>
                <td>¥${selectionPrice.toFixed(2)}</td>
                <td>¥${currentPrice.toFixed(2)}</td>
                <td class="${currentReturn >= 0 ? 'text-success' : 'text-danger'}">${currentReturn.toFixed(2)}%</td>
                <td>¥${highestPrice.toFixed(2)}</td>
                <td class="${highestReturn >= 0 ? 'text-success' : 'text-danger'}">${highestReturn.toFixed(2)}%</td>
            </tr>
        `;
    });
    
    html += `
                </tbody>
            </table>
        </div>
    `;
    
    stockInfo.innerHTML = html;
    modal.classList.add('active');
}

/**
 * 初始化K线图表
 * @param {string} containerId - 容器ID
 * @param {Object} data - K线数据
 */
function initKlineChart(containerId, data) {
    // 调用全局的initKlineChart函数
    if (window.initKlineChart) {
        window.initKlineChart(containerId, data);
    } else {
        console.error('全局initKlineChart函数不存在');
    }
}
