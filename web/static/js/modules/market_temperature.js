/**
 * 市场温度计模块
 */

// 全局状态
let marketTempCache = null;  // 缓存当前温度数据
let tempTrendCache = null;   // 缓存趋势数据

/**
 * 初始化市场温度计
 */
export async function initMarketTemperature() {
    console.log('初始化市场温度计');
    
    // 获取并显示当前温度
    await loadCurrentTemperature();
    
    // 每5分钟刷新一次
    setInterval(loadCurrentTemperature, 5 * 60 * 1000);
}

/**
 * 加载并显示当前市场温度
 */
export async function loadCurrentTemperature() {
    try {
        // 1. 首先尝试获取数据库中最新保存的温度数据
        let response = await fetch('/api/market-temperature/latest');
        let result = await response.json();
        
        if (result.success && result.data) {
            // 使用最新保存的温度数据
            marketTempCache = result.data;
            updateTemperatureBadge(result.data);
            return;
        }
        
        // 2. 如果没有最新数据，尝试计算当前日期的温度
        response = await fetch('/api/market-temperature/calculate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ use_cache: true })
        });
        
        result = await response.json();
        
        if (result.success) {
            marketTempCache = result.data;
            updateTemperatureBadge(result.data);
        } else {
            // 数据不可用时隐藏徽章
            const badge = document.getElementById('market-temp-badge');
            if (badge) badge.style.display = 'none';
        }
    } catch (error) {
        console.error('加载市场温度失败:', error);
    }
}

/**
 * 更新温度徽章显示
 * @param {Object} data - 温度数据
 */
function updateTemperatureBadge(data) {
    const badge = document.getElementById('market-temp-badge');
    const badgeTemp = document.getElementById('market-temp-value');
    const badgeStatus = document.getElementById('market-temp-status');
    const badgeDate = document.getElementById('market-temp-date');
    
    if (!badge) return;
    
    // 如果没有有效温度数据，隐藏徽章
    if (!data || data.temperature === null || data.temperature === undefined) {
        badge.style.display = 'none';
        return;
    }
    
    // 有温度数据时显示徽章
    badge.style.display = 'flex';
    
    // 更新日期显示
    if (badgeDate && data.trade_date) {
        // 格式化为 YYYY-MM-DD
        const formatted = `${data.trade_date.slice(0,4)}-${data.trade_date.slice(4,6)}-${data.trade_date.slice(6,8)}`;
        badgeDate.textContent = formatted;
    } else {
        badgeDate.textContent = '--';
    }
    
    // 更新温度值
    if (badgeTemp) {
        badgeTemp.textContent = data.temperature !== null ? data.temperature.toFixed(1) : '--';
    }
    
    // 更新状态文字
    if (badgeStatus) {
        badgeStatus.textContent = data.status || '--';
    }
    
    // 根据温度设置颜色
    const temp = data.temperature || 0;
    let bgColor, textColor;
    
    if (temp >= 80) {
        bgColor = '#ef4444';  // 红色 - 活跃
        textColor = '#ffffff';
    } else if (temp >= 65) {
        bgColor = '#f59e0b';  // 橙色 - 正常
        textColor = '#ffffff';
    } else if (temp >= 50) {
        bgColor = '#eab308';  // 黄色 - 偏冷
        textColor = '#1f2937';
    } else if (temp >= 30) {
        bgColor = '#3b82f6';  // 蓝色 - 寒冷
        textColor = '#ffffff';
    } else if (temp >= 15) {
        bgColor = '#6366f1';  // 靛蓝 - 冰封
        textColor = '#ffffff';
    } else {
        bgColor = '#1f2937';  // 深灰 - 极端
        textColor = '#ffffff';
    }
    
    badge.style.backgroundColor = bgColor;
    badge.style.color = textColor;
}

/**
 * 显示温度详情弹窗
 */
export async function showTemperatureDetail() {
    // 确保有最新数据
    if (!marketTempCache) {
        await loadCurrentTemperature();
    }
    
    if (!marketTempCache) {
        alert('加载温度数据失败');
        return;
    }
    
    const data = marketTempCache;
    
    // 格式化日期显示
    const formatDate = (dateStr) => {
        if (!dateStr) return '--';
        return `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}`;
    };
    
    const dateLabel = data.trade_date ? formatDate(data.trade_date) : '--';
    
    const content = `
        <div style="padding: 20px; min-width: 400px;">
            <!-- 当前状态头部 -->
            <div style="text-align: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb;">
                <div style="font-size: 14px; color: #6b7280; margin-bottom: 8px;">
                    ${dateLabel} 市场温度
                </div>
                <div style="font-size: 48px; font-weight: bold; color: ${getTempColor(data.temperature)};">
                    ${data.temperature !== null ? data.temperature.toFixed(1) : '--'}°
                </div>
                <div style="font-size: 18px; font-weight: 600; color: ${getTempColor(data.temperature)}; margin-top: 4px;">
                    ${data.status || '未知'}
                </div>
                <div style="font-size: 14px; color: #6b7280; margin-top: 8px;">
                    建议仓位: <span style="font-weight: bold; color: #374151;">${((data.position_ratio || 0) * 100).toFixed(0)}%</span>
                </div>
            </div>
            
            <!-- 狩猎场执行规则 -->
            <div style="background: #f9fafb; border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                <div style="font-size: 12px; font-weight: 600; color: #374151; margin-bottom: 4px;">狩猎场执行规则</div>
                <div style="font-size: 14px; color: #4b5563;">${data.action || '无特殊规则'}</div>
            </div>
            
            <!-- 四维度评分 -->
            <div style="margin-bottom: 16px;">
                <div style="font-size: 12px; font-weight: 600; color: #374151; margin-bottom: 12px;">各维度评分</div>
                
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="font-size: 13px; color: #4b5563;">涨跌家数比</span>
                        <span style="font-size: 13px; font-weight: 600; color: #374151;">${(data.up_down_ratio_score || 0).toFixed(1)}分</span>
                    </div>
                    <div class="progress-bar" style="height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; background: #3b82f6; width: ${data.up_down_ratio_score || 0}%; transition: width 0.3s;"></div>
                    </div>
                </div>
                
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="font-size: 13px; color: #4b5563;">跌停家数</span>
                        <span style="font-size: 13px; font-weight: 600; color: #374151;">${(data.limit_down_score || 0).toFixed(1)}分</span>
                    </div>
                    <div class="progress-bar" style="height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; background: #8b5cf6; width: ${data.limit_down_score || 0}%; transition: width 0.3s;"></div>
                    </div>
                </div>
                
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="font-size: 13px; color: #4b5563;">昨日涨停表现</span>
                        <span style="font-size: 13px; font-weight: 600; color: #374151;">${(data.limit_up_performance_score || 0).toFixed(1)}分</span>
                    </div>
                    <div class="progress-bar" style="height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; background: #10b981; width: ${data.limit_up_performance_score || 0}%; transition: width 0.3s;"></div>
                    </div>
                </div>
                
                <div style="margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span style="font-size: 13px; color: #4b5563;">成交额相对位置</span>
                        <span style="font-size: 13px; font-weight: 600; color: #374151;">${(data.volume_score || 0).toFixed(1)}分</span>
                    </div>
                    <div class="progress-bar" style="height: 8px; background: #e5e7eb; border-radius: 4px; overflow: hidden;">
                        <div style="height: 100%; background: #f59e0b; width: ${data.volume_score || 0}%; transition: width 0.3s;"></div>
                    </div>
                </div>
            </div>
            
            <!-- 原始数据 -->
            <div style="border-top: 1px solid #e5e7eb; padding-top: 16px;">
                <div style="font-size: 12px; font-weight: 600; color: #374151; margin-bottom: 12px;">原始数据</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 13px;">
                    <div>上涨家数: <span style="font-weight: 600;">${data.up_count || '--'}</span></div>
                    <div>下跌家数: <span style="font-weight: 600;">${data.down_count || '--'}</span></div>
                    <div>跌停家数: <span style="font-weight: 600;">${data.limit_down_count || '--'}</span></div>
                    <div>涨停均涨幅: <span style="font-weight: 600;">${data.avg_limit_up_change !== null ? data.avg_limit_up_change.toFixed(2) + '%' : '--'}</span></div>
                    <div>总成交额: <span style="font-weight: 600;">${data.total_volume !== null ? data.total_volume.toFixed(0) + '亿' : '--'}</span></div>
                    <div>量能比: <span style="font-weight: 600;">${data.volume_ma5_ratio !== null ? data.volume_ma5_ratio.toFixed(2) : '--'}</span></div>
                </div>
            </div>
            
            <!-- 操作按钮 -->
            <div style="margin-top: 20px; text-align: center;">
                <button onclick="showTemperatureTrend()" class="btn btn-primary" style="padding: 8px 16px; font-size: 13px;">
                    查看趋势图
                </button>
            </div>
        </div>
    `;
    
    showModal('市场温度详情', content);
}

/**
 * 显示温度趋势图
 */
export async function showTemperatureTrend() {
    closeModal();
    
    try {
        const response = await fetch('/api/market-temperature/trend?days=10');
        const result = await response.json();
        
        if (!result.success || !result.data.trend) {
            alert('加载趋势数据失败');
            return;
        }
        
        const trend = result.data.trend;
        
        // 创建趋势图弹窗内容
        const content = `
            <div style="padding: 20px; min-width: 600px;">
                <!-- 统计概览 -->
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px;">
                    <div style="text-align: center; padding: 12px; background: #f9fafb; border-radius: 6px;">
                        <div style="font-size: 12px; color: #6b7280;">平均温度</div>
                        <div style="font-size: 20px; font-weight: bold; color: #374151;">${(result.data.avg_temperature || 0).toFixed(1)}°</div>
                    </div>
                    <div style="text-align: center; padding: 12px; background: #f9fafb; border-radius: 6px;">
                        <div style="font-size: 12px; color: #6b7280;">最高温度</div>
                        <div style="font-size: 20px; font-weight: bold; color: #22c55e;">${(result.data.max_temperature || 0).toFixed(1)}°</div>
                    </div>
                    <div style="text-align: center; padding: 12px; background: #f9fafb; border-radius: 6px;">
                        <div style="font-size: 12px; color: #6b7280;">最低温度</div>
                        <div style="font-size: 20px; font-weight: bold; color: #3b82f6;">${(result.data.min_temperature || 0).toFixed(1)}°</div>
                    </div>
                    <div style="text-align: center; padding: 12px; background: #f9fafb; border-radius: 6px;">
                        <div style="font-size: 12px; color: #6b7280;">当前状态</div>
                        <div style="font-size: 16px; font-weight: bold; color: ${getTempColor(result.data.latest_temperature)};">${result.data.latest_status || '--'}</div>
                    </div>
                </div>
                
                <!-- 趋势图表 -->
                <div style="height: 300px; margin-bottom: 16px;">
                    <canvas id="temp-trend-chart"></canvas>
                </div>
                
                <!-- 趋势数据表 -->
                <div style="max-height: 200px; overflow-y: auto;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                        <thead style="position: sticky; top: 0; background: #f9fafb;">
                            <tr>
                                <th style="text-align: left; padding: 8px; border-bottom: 1px solid #e5e7eb;">日期</th>
                                <th style="text-align: right; padding: 8px; border-bottom: 1px solid #e5e7eb;">温度</th>
                                <th style="text-align: center; padding: 8px; border-bottom: 1px solid #e5e7eb;">状态</th>
                                <th style="text-align: right; padding: 8px; border-bottom: 1px solid #e5e7eb;">仓位</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${trend.map(item => `
                                <tr>
                                    <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">${item.trade_date}</td>
                                    <td style="text-align: right; padding: 8px; border-bottom: 1px solid #e5e7eb; font-weight: 600; color: ${getTempColor(item.temperature)};">${(item.temperature || 0).toFixed(1)}°</td>
                                    <td style="text-align: center; padding: 8px; border-bottom: 1px solid #e5e7eb;">${item.status || '--'}</td>
                                    <td style="text-align: right; padding: 8px; border-bottom: 1px solid #e5e7eb;">${((item.position_ratio || 0) * 100).toFixed(0)}%</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        
        showModal('市场温度趋势', content);
        
        // 渲染图表
        setTimeout(() => renderTempTrendChart(trend), 100);
        
    } catch (error) {
        console.error('加载趋势数据失败:', error);
        alert('加载趋势数据失败');
    }
}

/**
 * 渲染温度趋势图表
 * @param {Array} trend - 趋势数据
 */
function renderTempTrendChart(trend) {
    const canvas = document.getElementById('temp-trend-chart');
    if (!canvas) return;
    
    // 使用简单的Canvas绑制
    const ctx = canvas.getContext('2d');
    const width = canvas.width = canvas.parentElement.clientWidth;
    const height = canvas.height = 280;
    
    // 清除画布
    ctx.clearRect(0, 0, width, height);
    
    // 数据准备
    const labels = trend.map(item => item.trade_date.slice(4, 8));  // MM-DD格式
    const temperatures = trend.map(item => item.temperature || 0);
    const minTemp = 0;
    const maxTemp = 100;
    
    // 绘制网格
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = 40 + (height - 80) * i / 5;
        ctx.beginPath();
        ctx.moveTo(60, y);
        ctx.lineTo(width - 20, y);
        ctx.stroke();
        
        // Y轴标签
        ctx.fillStyle = '#6b7280';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText((maxTemp - (maxTemp - minTemp) * i / 5).toFixed(0) + '°', 55, y + 4);
    }
    
    // X轴标签
    ctx.textAlign = 'center';
    labels.forEach((label, i) => {
        const x = 70 + (width - 100) * i / (labels.length - 1 || 1);
        ctx.fillText(label, x, height - 10);
    });
    
    // 绘制温度区域填充
    const gradient = ctx.createLinearGradient(0, 40, 0, height - 30);
    gradient.addColorStop(0, 'rgba(239, 68, 68, 0.3)');
    gradient.addColorStop(0.3, 'rgba(245, 158, 11, 0.2)');
    gradient.addColorStop(0.5, 'rgba(234, 179, 8, 0.1)');
    gradient.addColorStop(0.7, 'rgba(59, 130, 246, 0.1)');
    gradient.addColorStop(1, 'rgba(99, 102, 241, 0.1)');
    
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(70, height - 30);
    temperatures.forEach((temp, i) => {
        const x = 70 + (width - 100) * i / (temperatures.length - 1 || 1);
        const y = 40 + (height - 80) * (1 - temp / maxTemp);
        ctx.lineTo(x, y);
    });
    ctx.lineTo(70 + (width - 100), height - 30);
    ctx.closePath();
    ctx.fill();
    
    // 绘制温度折线
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    temperatures.forEach((temp, i) => {
        const x = 70 + (width - 100) * i / (temperatures.length - 1 || 1);
        const y = 40 + (height - 80) * (1 - temp / maxTemp);
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
    
    // 绘制数据点和数值
    temperatures.forEach((temp, i) => {
        const x = 70 + (width - 100) * i / (temperatures.length - 1 || 1);
        const y = 40 + (height - 80) * (1 - temp / maxTemp);
        
        // 数据点
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = getTempColor(temp);
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // 数值标签
        ctx.fillStyle = '#374151';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(temp.toFixed(1) + '°', x, y - 10);
    });
    
    // 绘制参考线
    [30, 50, 65, 80].forEach(level => {
        const y = 40 + (height - 80) * (1 - level / maxTemp);
        ctx.strokeStyle = level === 30 || level === 80 ? '#ef4444' : '#d1d5db';
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(60, y);
        ctx.lineTo(width - 20, y);
        ctx.stroke();
        ctx.setLineDash([]);
    });
}

/**
 * 获取温度对应的颜色
 * @param {number} temp - 温度值
 * @returns {string} 颜色值
 */
function getTempColor(temp) {
    if (temp === null || temp === undefined) return '#6b7280';
    if (temp >= 80) return '#ef4444';      // 红色 - 活跃
    if (temp >= 65) return '#f59e0b';       // 橙色 - 正常
    if (temp >= 50) return '#eab308';      // 黄色 - 偏冷
    if (temp >= 30) return '#3b82f6';      // 蓝色 - 寒冷
    if (temp >= 15) return '#6366f1';      // 靛蓝 - 冰封
    return '#1f2937';                       // 深灰 - 极端
}

/**
 * 显示模态框
 * @param {string} title - 标题
 * @param {string} content - 内容HTML
 */
function showModal(title, content) {
    // 创建遮罩层
    const overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; align-items: center; justify-content: center;';
    overlay.onclick = (e) => { if (e.target === overlay) closeModal(); };
    
    // 创建模态框
    const modal = document.createElement('div');
    modal.style.cssText = 'background: white; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.15); max-width: 90%; max-height: 90%; overflow: auto;';
    
    // 创建头部
    const header = document.createElement('div');
    header.style.cssText = 'padding: 16px 20px; border-bottom: 1px solid #e5e7eb; display: flex; justify-content: space-between; align-items: center;';
    
    const titleEl = document.createElement('h3');
    titleEl.style.cssText = 'margin: 0; font-size: 16px; font-weight: 600; color: #374151;';
    titleEl.textContent = title;
    
    const closeBtn = document.createElement('button');
    closeBtn.style.cssText = 'background: none; border: none; font-size: 20px; cursor: pointer; color: #6b7280; padding: 4px;';
    closeBtn.textContent = '×';
    closeBtn.onclick = closeModal;  // 直接引用，不使用字符串
    
    header.appendChild(titleEl);
    header.appendChild(closeBtn);
    
    // 创建内容区
    const contentDiv = document.createElement('div');
    contentDiv.id = 'modal-content';
    contentDiv.innerHTML = content;
    
    modal.appendChild(header);
    modal.appendChild(contentDiv);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
    
    // 绑定ESC关闭
    document.addEventListener('keydown', function escClose(e) {
        if (e.key === 'Escape') {
            closeModal();
            document.removeEventListener('keydown', escClose);
        }
    });
}

/**
 * 关闭模态框
 */
function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) {
        overlay.remove();
    }
}

// 暴露到全局
window.closeModal = closeModal;
window.showTemperatureTrend = showTemperatureTrend;
