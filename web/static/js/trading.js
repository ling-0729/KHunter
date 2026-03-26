/**
 * 模拟交易模块 - 前端交易功能实现
 * 提供账户总览、买入、卖出、持仓查询、交易历史等功能
 */

// ==================== 全局配置 ====================

const TRADING_API_BASE = '/api/trading';
const DEFAULT_ACCOUNT_ID = 'default_account';

// 当前账户ID（可从登录信息获取）
let currentAccountId = DEFAULT_ACCOUNT_ID;

// ==================== 工具函数 ====================

/**
 * 格式化数字为货币显示
 * @param {number} value - 数值
 * @param {number} decimals - 小数位数，默认2
 * @returns {string} 格式化后的字符串
 */
function formatCurrency(value, decimals = 2) {
    // 检查输入有效性
    if (value === null || value === undefined) {
        return '¥0.00';
    }
    // 转换为数字并格式化
    const num = parseFloat(value);
    return '¥' + num.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * 格式化百分比显示
 * @param {number} value - 百分比值
 * @param {number} decimals - 小数位数，默认2
 * @returns {string} 格式化后的字符串
 */
function formatPercent(value, decimals = 2) {
    // 检查输入有效性
    if (value === null || value === undefined) {
        return '0.00%';
    }
    // 转换为数字并格式化
    const num = parseFloat(value);
    return num.toFixed(decimals) + '%';
}

/**
 * 显示提示信息
 * @param {string} message - 提示信息
 * @param {string} type - 类型：success, error, warning, info
 */
function showNotification(message, type = 'info') {
    // 创建提示元素
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // 添加到页面
    document.body.appendChild(notification);
    
    // 3秒后移除
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

/**
 * 发送API请求
 * @param {string} method - HTTP方法
 * @param {string} endpoint - API端点
 * @param {object} data - 请求数据
 * @returns {Promise} 返回Promise
 */
async function apiRequest(method, endpoint, data = null) {
    // 构建完整URL
    const url = TRADING_API_BASE + endpoint;
    
    // 构建请求选项
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json'
        }
    };
    
    // 如果有数据，添加到请求体
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    try {
        // 发送请求
        const response = await fetch(url, options);
        const result = await response.json();
        
        // 检查响应状态
        if (!result.success) {
            throw new Error(result.message || '请求失败');
        }
        
        return result.data;
    } catch (error) {
        // 记录错误并抛出
        console.error('API请求失败:', error);
        throw error;
    }
}

/**
 * 获取股票信息（包括名称）
 * @param {string} code - 股票代码
 * @returns {Promise} 返回股票信息
 */
async function getStockInfo(code) {
    try {
        // 调用API获取股票信息
        const url = TRADING_API_BASE + `/stock/info?code=${code}`;
        console.log('获取股票信息，URL:', url);
        
        // 发送请求
        const response = await fetch(url);
        const result = await response.json();
        
        console.log('股票信息API响应:', result);
        
        // 检查响应状态
        if (!result.success) {
            console.error('获取股票信息失败:', result.message);
            return null;
        }
        
        return result.data;
    } catch (error) {
        // 记录错误
        console.error('获取股票信息异常:', error);
        return null;
    }
}

/**
 * 获取股票的当天价格区间
 * @param {string} code - 股票代码
 * @returns {Promise} 返回价格区间信息
 */
async function getPriceRange(code) {
    try {
        // 调用API获取价格区间
        const url = TRADING_API_BASE + `/stock/price-range?code=${code}`;
        console.log('获取价格区间，URL:', url);
        
        // 发送请求
        const response = await fetch(url);
        const result = await response.json();
        
        console.log('价格区间API响应:', result);
        
        // 检查响应状态
        if (!result.success) {
            console.error('获取价格区间失败:', result.message);
            return null;
        }
        
        return result.data;
    } catch (error) {
        // 记录错误
        console.error('获取价格区间异常:', error);
        return null;
    }
}

/**
 * 验证交易价格是否在当天价格区间内
 * @param {number} price - 交易价格
 * @param {string} code - 股票代码
 * @param {string} type - 交易类型：buy 或 sell
 * @returns {Promise} 返回验证结果 {valid: boolean, message: string}
 */
async function validatePrice(price, code, type) {
    try {
        // 获取价格区间
        const priceRange = await getPriceRange(code);
        
        // 如果获取失败，返回错误
        if (!priceRange) {
            return {
                valid: false,
                message: '无法获取该股票的实时价格数据'
            };
        }
        
        // 检查价格是否在区间内
        const lowPrice = priceRange.low_price;
        const highPrice = priceRange.high_price;
        
        // 验证价格
        if (price < lowPrice || price > highPrice) {
            const typeText = type === 'buy' ? '买入' : '卖出';
            return {
                valid: false,
                message: `${typeText}价格 ${price.toFixed(2)} 不在当天价格区间内，当天价格区间：${lowPrice.toFixed(2)} - ${highPrice.toFixed(2)} 元`
            };
        }
        
        // 价格有效
        return {
            valid: true,
            message: null
        };
    } catch (error) {
        // 记录错误
        console.error('价格验证失败:', error);
        return {
            valid: false,
            message: '价格验证失败，请重试'
        };
    }
}

// ==================== 账户总览功能 ====================

/**
 * 获取账户总览信息
 * @returns {Promise} 返回账户信息
 */
async function getAccountSummary() {
    try {
        // 调用API获取账户总览
        const data = await apiRequest('GET', `/account/summary?account_id=${currentAccountId}`);
        return data;
    } catch (error) {
        // 显示错误提示
        showNotification('获取账户信息失败: ' + error.message, 'error');
        throw error;
    }
}

/**
 * 显示账户总览页面
 */
async function showAccountSummary() {
    try {
        // 获取账户信息
        const account = await getAccountSummary();
        
        // 构建账户总览HTML
        const summaryHtml = `
            <div class="account-summary">
                <div class="account-card">
                    <div class="account-card-label">总资产</div>
                    <div class="account-card-value">${formatCurrency(account.total_assets)}</div>
                </div>
                <div class="account-card">
                    <div class="account-card-label">可用资金</div>
                    <div class="account-card-value">${formatCurrency(account.current_cash)}</div>
                </div>
                <div class="account-card">
                    <div class="account-card-label">总收益</div>
                    <div class="account-card-value ${account.total_profit_loss >= 0 ? 'profit' : 'loss'}">
                        ${formatCurrency(account.total_profit_loss)}
                    </div>
                </div>
                <div class="account-card">
                    <div class="account-card-label">收益率</div>
                    <div class="account-card-value ${account.profit_loss_rate >= 0 ? 'profit' : 'loss'}">
                        ${formatPercent(account.profit_loss_rate)}
                    </div>
                </div>
            </div>
        `;
        
        // 更新账户总览容器
        const summaryContainer = document.getElementById('trading-account-summary');
        if (summaryContainer) {
            summaryContainer.innerHTML = summaryHtml;
        }
        
        // 构建快速操作按钮HTML
        const actionsHtml = `
            <div class="quick-actions">
                <button class="quick-action-btn" onclick="showBuyPage()">
                    <span>💰</span> 买入
                </button>
                <button class="quick-action-btn" onclick="showSellPage()">
                    <span>📊</span> 卖出
                </button>
                <button class="quick-action-btn" onclick="showPositions()">
                    <span>📈</span> 持仓
                </button>
                <button class="quick-action-btn" onclick="showTransactions()">
                    <span>📋</span> 历史
                </button>
            </div>
        `;
        
        // 更新快速操作容器
        const actionsContainer = document.getElementById('trading-quick-actions');
        if (actionsContainer) {
            actionsContainer.innerHTML = actionsHtml;
        }
        
        // 显示账户总览页面
        updateMainContent(`
            <div class="trading-operation-card">
                <h3>📊 账户总览</h3>
                <p style="color: var(--text-muted); margin-bottom: 16px;">
                    欢迎使用模拟交易系统，请选择下方操作开始交易
                </p>
            </div>
        `);
    } catch (error) {
        // 显示错误信息
        console.error('加载账户总览失败:', error);
        showNotification('加载账户总览失败: ' + error.message, 'error');
    }
}

// ==================== 买入功能 ====================

/**
 * 显示买入页面
 */
function showBuyPage() {
    // 构建HTML内容
    const html = `
        <div class="trading-container">
            <h2>买入</h2>
            <form id="buyForm" onsubmit="handleBuy(event)">
                <div class="form-group">
                    <label>股票代码</label>
                    <input type="text" id="buyCode" placeholder="例如: 000001" required onchange="updateBuyPriceRange()">
                </div>
                <div class="form-group">
                    <div id="buyPriceRangeInfo" class="price-range-info" style="display: none;">
                        <span id="buyPriceRangeText"></span>
                    </div>
                </div>
                <div class="form-group">
                    <label>股票名称</label>
                    <input type="text" id="buyName" placeholder="例如: 平安银行" required>
                </div>
                <div class="form-group">
                    <label>买入数量</label>
                    <input type="number" id="buyQuantity" placeholder="100" min="1" required>
                </div>
                <div class="form-group">
                    <label>买入价格</label>
                    <input type="number" id="buyPrice" placeholder="10.50" step="0.01" min="0.01" required>
                </div>
                <div class="form-group">
                    <label>交易日期</label>
                    <input type="date" id="buyDate" required>
                </div>
                <div class="form-summary">
                    <div class="summary-item">
                        <label>预计成本</label>
                        <value id="buyCost">¥0.00</value>
                    </div>
                    <div class="summary-item">
                        <label>手续费</label>
                        <value id="buyCommission">¥0.00</value>
                    </div>
                    <div class="summary-item">
                        <label>总成本</label>
                        <value id="buyTotal">¥0.00</value>
                    </div>
                </div>
                <div class="form-buttons">
                    <button type="submit">确认买入</button>
                    <button type="button" onclick="showAccountSummary()">取消</button>
                </div>
            </form>
        </div>
    `;
    
    // 更新页面内容
    updateMainContent(html);
    
    // 设置默认日期为今天
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('buyDate').value = today;
    
    // 添加实时计算事件
    document.getElementById('buyQuantity').addEventListener('change', calculateBuyCost);
    document.getElementById('buyPrice').addEventListener('change', calculateBuyCost);
}

/**
 * 更新买入页面的价格区间显示
 */
async function updateBuyPriceRange() {
    // 获取股票代码
    const code = document.getElementById('buyCode').value;
    
    console.log('更新买入价格区间，代码:', code);
    
    // 如果代码为空，隐藏价格区间信息
    if (!code) {
        document.getElementById('buyPriceRangeInfo').style.display = 'none';
        return;
    }
    
    try {
        // 并行获取股票信息和价格区间
        const [stockInfo, priceRange] = await Promise.all([
            getStockInfo(code),
            getPriceRange(code)
        ]);
        
        console.log('获取到的股票信息:', stockInfo);
        console.log('获取到的价格区间:', priceRange);
        
        // 如果获取股票信息成功，自动填充股票名称
        if (stockInfo && stockInfo.name) {
            console.log('自动填充股票名称:', stockInfo.name);
            document.getElementById('buyName').value = stockInfo.name;
        }
        
        // 如果获取价格区间成功，显示价格区间
        if (priceRange) {
            const message = `当天价格区间：${priceRange.low_price.toFixed(2)} - ${priceRange.high_price.toFixed(2)} 元`;
            console.log('显示价格区间信息:', message);
            document.getElementById('buyPriceRangeText').textContent = message;
            document.getElementById('buyPriceRangeInfo').style.display = 'block';
        } else {
            // 获取失败，隐藏价格区间信息
            console.log('获取价格区间失败，隐藏信息');
            document.getElementById('buyPriceRangeInfo').style.display = 'none';
        }
    } catch (error) {
        // 记录错误
        console.error('更新买入页面异常:', error);
        document.getElementById('buyPriceRangeInfo').style.display = 'none';
    }
}

/**
 * 计算买入成本
 */
function calculateBuyCost() {
    // 获取输入值
    const quantity = parseInt(document.getElementById('buyQuantity').value) || 0;
    const price = parseFloat(document.getElementById('buyPrice').value) || 0;
    
    // 计算成本
    const cost = quantity * price;
    const commission = Math.max(cost * 0.005, 5);
    const total = cost + commission;
    
    // 更新显示
    document.getElementById('buyCost').textContent = formatCurrency(cost);
    document.getElementById('buyCommission').textContent = formatCurrency(commission);
    document.getElementById('buyTotal').textContent = formatCurrency(total);
}

/**
 * 处理买入提交
 * @param {Event} event - 表单事件
 */
async function handleBuy(event) {
    // 阻止默认提交
    event.preventDefault();
    
    try {
        // 获取表单数据
        const stockCode = document.getElementById('buyCode').value;
        const price = parseFloat(document.getElementById('buyPrice').value);
        
        // 验证买入价格
        const validation = await validatePrice(price, stockCode, 'buy');
        
        // 如果价格验证失败，显示警告并返回
        if (!validation.valid) {
            showNotification(validation.message, 'warning');
            return;
        }
        
        // 构建买入数据
        const buyData = {
            account_id: currentAccountId,
            stock_code: stockCode,
            stock_name: document.getElementById('buyName').value,
            quantity: parseInt(document.getElementById('buyQuantity').value),
            price: price,
            transaction_date: document.getElementById('buyDate').value
        };
        
        // 调用API执行买入
        await apiRequest('POST', '/buy', buyData);
        
        // 显示成功提示
        showNotification('买入成功', 'success');
        
        // 返回账户总览
        setTimeout(() => {
            showAccountSummary();
        }, 1000);
    } catch (error) {
        // 显示错误提示
        showNotification('买入失败: ' + error.message, 'error');
    }
}

// ==================== 卖出功能 ====================

/**
 * 显示卖出页面
 */
async function showSellPage() {
    try {
        // 获取持仓列表
        const positionsData = await apiRequest('GET', `/account/positions?account_id=${currentAccountId}`);
        const positions = positionsData.positions || [];
        
        // 构建持仓选项HTML
        let positionOptions = '<option value="">请选择持仓</option>';
        positions.forEach(pos => {
            positionOptions += `<option value="${pos.stock_code}" data-quantity="${pos.quantity}" data-cost="${pos.cost_price}">
                ${pos.stock_code} ${pos.stock_name} (${pos.quantity}股 成本${pos.cost_price})
            </option>`;
        });
        
        // 构建HTML内容
        const html = `
            <div class="trading-container">
                <h2>卖出</h2>
                <form id="sellForm" onsubmit="handleSell(event)">
                    <div class="form-group">
                        <label>选择持仓</label>
                        <select id="sellPosition" onchange="updateSellInfo()" required>
                            ${positionOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <div id="sellPriceRangeInfo" class="price-range-info" style="display: none;">
                            <span id="sellPriceRangeText"></span>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>卖出数量</label>
                        <input type="number" id="sellQuantity" placeholder="50" min="1" required>
                    </div>
                    <div class="form-group">
                        <label>卖出价格</label>
                        <input type="number" id="sellPrice" placeholder="11.00" step="0.01" min="0.01" required>
                    </div>
                    <div class="form-group">
                        <label>交易日期</label>
                        <input type="date" id="sellDate" required>
                    </div>
                    <div class="form-summary">
                        <div class="summary-item">
                            <label>卖出金额</label>
                            <value id="sellAmount">¥0.00</value>
                        </div>
                        <div class="summary-item">
                            <label>手续费</label>
                            <value id="sellCommission">¥0.00</value>
                        </div>
                        <div class="summary-item">
                            <label>印花税</label>
                            <value id="sellTax">¥0.00</value>
                        </div>
                        <div class="summary-item">
                            <label>预计收益</label>
                            <value id="sellProfit">¥0.00</value>
                        </div>
                    </div>
                    <div class="form-buttons">
                        <button type="submit">确认卖出</button>
                        <button type="button" onclick="showAccountSummary()">取消</button>
                    </div>
                </form>
            </div>
        `;
        
        // 更新页面内容
        updateMainContent(html);
        
        // 设置默认日期为今天
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('sellDate').value = today;
        
        // 添加实时计算事件
        document.getElementById('sellQuantity').addEventListener('change', calculateSellProfit);
        document.getElementById('sellPrice').addEventListener('change', calculateSellProfit);
    } catch (error) {
        // 显示错误提示
        showNotification('加载持仓列表失败: ' + error.message, 'error');
    }
}

/**
 * 更新卖出信息
 */
async function updateSellInfo() {
    // 获取选中的持仓
    const select = document.getElementById('sellPosition');
    const option = select.options[select.selectedIndex];
    
    console.log('更新卖出信息，持仓代码:', option.value);
    
    // 更新数量限制
    if (option.value) {
        const maxQuantity = option.getAttribute('data-quantity');
        document.getElementById('sellQuantity').max = maxQuantity;
        
        // 获取并显示价格区间
        try {
            const priceRange = await getPriceRange(option.value);
            
            console.log('获取到的卖出价格区间:', priceRange);
            
            // 如果获取成功，显示价格区间
            if (priceRange) {
                const message = `当天价格区间：${priceRange.low_price.toFixed(2)} - ${priceRange.high_price.toFixed(2)} 元`;
                console.log('显示卖出价格区间信息:', message);
                document.getElementById('sellPriceRangeText').textContent = message;
                document.getElementById('sellPriceRangeInfo').style.display = 'block';
            } else {
                // 获取失败，隐藏价格区间信息
                console.log('获取卖出价格区间失败，隐藏信息');
                document.getElementById('sellPriceRangeInfo').style.display = 'none';
            }
        } catch (error) {
            // 记录错误
            console.error('获取卖出价格区间异常:', error);
            document.getElementById('sellPriceRangeInfo').style.display = 'none';
        }
    } else {
        // 未选择持仓，隐藏价格区间信息
        document.getElementById('sellPriceRangeInfo').style.display = 'none';
    }
    
    // 重新计算收益
    calculateSellProfit();
}

/**
 * 计算卖出收益
 */
function calculateSellProfit() {
    // 获取输入值
    const quantity = parseInt(document.getElementById('sellQuantity').value) || 0;
    const price = parseFloat(document.getElementById('sellPrice').value) || 0;
    
    // 获取成本价
    const select = document.getElementById('sellPosition');
    const option = select.options[select.selectedIndex];
    const costPrice = parseFloat(option.getAttribute('data-cost')) || 0;
    
    // 计算金额
    const amount = quantity * price;
    const commission = Math.max(amount * 0.005, 5);
    const tax = amount * 0.001;
    const cost = quantity * costPrice;
    const profit = amount - cost - commission - tax;
    
    // 更新显示
    document.getElementById('sellAmount').textContent = formatCurrency(amount);
    document.getElementById('sellCommission').textContent = formatCurrency(commission);
    document.getElementById('sellTax').textContent = formatCurrency(tax);
    document.getElementById('sellProfit').textContent = formatCurrency(profit);
}

/**
 * 处理卖出提交
 * @param {Event} event - 表单事件
 */
async function handleSell(event) {
    // 阻止默认提交
    event.preventDefault();
    
    try {
        // 获取表单数据
        const stockCode = document.getElementById('sellPosition').value;
        const price = parseFloat(document.getElementById('sellPrice').value);
        
        // 验证卖出价格
        const validation = await validatePrice(price, stockCode, 'sell');
        
        // 如果价格验证失败，显示警告并返回
        if (!validation.valid) {
            showNotification(validation.message, 'warning');
            return;
        }
        
        // 构建卖出数据
        const sellData = {
            account_id: currentAccountId,
            stock_code: stockCode,
            quantity: parseInt(document.getElementById('sellQuantity').value),
            price: price,
            transaction_date: document.getElementById('sellDate').value
        };
        
        // 调用API执行卖出
        await apiRequest('POST', '/sell', sellData);
        
        // 显示成功提示
        showNotification('卖出成功', 'success');
        
        // 返回账户总览
        setTimeout(() => {
            showAccountSummary();
        }, 1000);
    } catch (error) {
        // 显示错误提示
        showNotification('卖出失败: ' + error.message, 'error');
    }
}

// ==================== 持仓查询功能 ====================

/**
 * 显示持仓列表
 */
async function showPositions() {
    try {
        // 获取持仓列表
        const positionsData = await apiRequest('GET', `/account/positions?account_id=${currentAccountId}`);
        const positions = positionsData.positions || [];
        
        // 构建表格HTML
        let tableHtml = `
            <h2>持仓明细</h2>
            <table class="positions-table">
                <thead>
                    <tr>
                        <th>代码</th>
                        <th>名称</th>
                        <th>数量</th>
                        <th>成本价</th>
                        <th>当前价</th>
                        <th>市值</th>
                        <th>收益</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        // 添加持仓行
        let totalMarketValue = 0;
        let totalProfit = 0;
        positions.forEach(pos => {
            totalMarketValue += pos.market_value;
            totalProfit += pos.profit_loss;
            tableHtml += `
                <tr>
                    <td>${pos.stock_code}</td>
                    <td>${pos.stock_name}</td>
                    <td>${pos.quantity}</td>
                    <td>${formatCurrency(pos.cost_price)}</td>
                    <td>${formatCurrency(pos.current_price)}</td>
                    <td>${formatCurrency(pos.market_value)}</td>
                    <td class="${pos.profit_loss >= 0 ? 'positive' : 'negative'}">
                        ${formatCurrency(pos.profit_loss)}
                    </td>
                </tr>
            `;
        });
        
        // 添加合计行
        tableHtml += `
                </tbody>
                <tfoot>
                    <tr>
                        <td colspan="5">合计</td>
                        <td>${formatCurrency(totalMarketValue)}</td>
                        <td class="${totalProfit >= 0 ? 'positive' : 'negative'}">
                            ${formatCurrency(totalProfit)}
                        </td>
                    </tr>
                </tfoot>
            </table>
        `;
        
        // 更新positions-content容器
        const positionsContent = document.getElementById('positions-content');
        if (positionsContent) {
            positionsContent.innerHTML = tableHtml;
        } else {
            console.error('找不到positions-content容器');
        }
    } catch (error) {
        // 显示错误提示
        showNotification('加载持仓列表失败: ' + error.message, 'error');
    }
}

// ==================== 交易历史功能 ====================

/**
 * 显示交易历史
 * @param {number} page - 页码，默认1
 */
async function showTransactions(page = 1) {
    try {
        // 获取交易历史
        const transData = await apiRequest('GET', 
            `/account/transactions?account_id=${currentAccountId}&page=${page}&limit=20`);
        const transactions = transData.transactions || [];
        const total = transData.total || 0;
        const totalPages = transData.total_pages || 1;
        
        // 构建表格HTML
        let tableHtml = `
            <h2>交易历史</h2>
            <table class="transactions-table">
                <thead>
                    <tr>
                        <th>日期</th>
                        <th>代码</th>
                        <th>名称</th>
                        <th>类型</th>
                        <th>数量</th>
                        <th>价格</th>
                        <th>金额</th>
                        <th>手续费</th>
                    </tr>
                </thead>
                <tbody>
        `;
        
        // 添加交易行
        transactions.forEach(trans => {
            const typeText = trans.transaction_type === 'BUY' ? '买入' : '卖出';
            tableHtml += `
                <tr>
                    <td>${trans.transaction_date}</td>
                    <td>${trans.stock_code}</td>
                    <td>${trans.stock_name}</td>
                    <td>${typeText}</td>
                    <td>${trans.quantity}</td>
                    <td>${formatCurrency(trans.price)}</td>
                    <td>${formatCurrency(trans.amount)}</td>
                    <td>${formatCurrency(trans.commission)}</td>
                </tr>
            `;
        });
        
        tableHtml += `
                </tbody>
            </table>
            <div class="pagination">
                第 ${page} 页 / 共 ${totalPages} 页
                ${page > 1 ? `<button onclick="showTransactions(${page - 1})">上一页</button>` : ''}
                ${page < totalPages ? `<button onclick="showTransactions(${page + 1})">下一页</button>` : ''}
            </div>
        `;
        
        // 更新transactions-content容器
        const transactionsContent = document.getElementById('transactions-content');
        if (transactionsContent) {
            transactionsContent.innerHTML = tableHtml;
        } else {
            console.error('找不到transactions-content容器');
        }
    } catch (error) {
        // 显示错误提示
        showNotification('加载交易历史失败: ' + error.message, 'error');
    }
}

// ==================== 页面管理 ====================

/**
 * 更新主内容区域
 * @param {string} html - HTML内容
 */
function updateMainContent(html) {
    // 获取交易页面的主内容容器
    const mainContent = document.getElementById('trading-main-content');
    
    // 更新内容
    if (mainContent) {
        mainContent.innerHTML = html;
    } else {
        console.error('找不到trading-main-content容器');
    }
}

/**
 * 初始化交易模块
 * 根据当前页面显示不同的内容：
 * - trading: 账户总览
 * - positions: 持仓明细
 * - transactions: 交易历史
 */
function initTrading() {
    // 根据当前页面显示不同的内容
    if (currentPage === 'positions') {
        // 显示持仓明细
        showPositions();
    } else if (currentPage === 'transactions') {
        // 显示交易历史
        showTransactions();
    } else {
        // 默认显示账户总览（trading页面）
        showAccountSummary();
    }
}

// 导出函数供HTML调用
window.showAccountSummary = showAccountSummary;
window.showBuyPage = showBuyPage;
window.showSellPage = showSellPage;
window.showPositions = showPositions;
window.showTransactions = showTransactions;
window.handleBuy = handleBuy;
window.handleSell = handleSell;
window.initTrading = initTrading;
window.updateBuyPriceRange = updateBuyPriceRange;
window.updateSellInfo = updateSellInfo;
window.calculateBuyCost = calculateBuyCost;
window.calculateSellProfit = calculateSellProfit;


// ==================== 账户管理功能 ====================

/**
 * 初始化账户选择器
 * 加载所有账户并显示在下拉菜单中
 */
async function initAccountSelector() {
    try {
        // 调用API获取所有账户
        const response = await fetch('/api/trading/accounts');
        const result = await response.json();
        
        // 检查响应状态
        if (!result.success) {
            console.error('获取账户列表失败:', result.message);
            return;
        }
        
        // 获取账户列表
        const accounts = result.data.accounts || [];
        
        // 如果没有账户，隐藏选择器
        if (accounts.length === 0) {
            console.warn('没有可用的账户');
            return;
        }
        
        // 构建选项HTML
        let optionsHtml = '';
        accounts.forEach(account => {
            optionsHtml += `<option value="${account.account_id}">${account.account_name}</option>`;
        });
        
        // 更新下拉菜单
        const selector = document.getElementById('account-selector');
        if (selector) {
            selector.innerHTML = optionsHtml;
            // 设置当前账户为第一个账户
            if (accounts.length > 0) {
                currentAccountId = accounts[0].account_id;
                selector.value = currentAccountId;
            }
        }
        
        // 显示账户选择器容器
        const container = document.getElementById('account-selector-container');
        if (container) {
            container.style.display = 'block';
        }
        
        console.log('账户选择器初始化成功，当前账户:', currentAccountId);
    } catch (error) {
        // 记录错误
        console.error('初始化账户选择器失败:', error);
    }
}

/**
 * 切换账户
 * 当用户选择不同的账户时调用
 */
async function switchAccount() {
    try {
        // 获取选中的账户ID
        const selector = document.getElementById('account-selector');
        const newAccountId = selector.value;
        
        // 如果账户ID为空，返回
        if (!newAccountId) {
            return;
        }
        
        // 验证账户是否存在
        const response = await fetch(`/api/trading/current-account?account_id=${newAccountId}`);
        const result = await response.json();
        
        // 检查响应状态
        if (!result.success) {
            showNotification('账户不存在', 'error');
            return;
        }
        
        // 更新当前账户ID
        currentAccountId = newAccountId;
        
        // 显示切换成功提示
        const accountName = result.data.account_name;
        showNotification(`已切换到账户: ${accountName}`, 'success');
        
        // 刷新交易页面数据
        if (document.getElementById('trading-page').style.display !== 'none') {
            showAccountSummary();
        }
        
        console.log('账户切换成功，当前账户:', currentAccountId);
    } catch (error) {
        // 显示错误提示
        showNotification('切换账户失败: ' + error.message, 'error');
        console.error('切换账户异常:', error);
    }
}

/**
 * 页面加载时初始化账户选择器
 */
document.addEventListener('DOMContentLoaded', function() {
    // 初始化账户选择器
    initAccountSelector();
});
