/**
 * 风控模块 - VaR仪表盘展示
 */

export class RiskModule {
    constructor() {
        this.riskStatus = null;
        this.riskHistory = [];
    }

    /**
     * 初始化风控模块
     */
    async init() {
        console.log('初始化风控模块');
        
        // 加载风控状态
        await this.loadRiskStatus();
        
        // 加载风控历史
        await this.loadRiskHistory();
        
        // 更新首页统计卡片
        if (typeof updateRiskCard === 'function') {
            updateRiskCard(this.riskStatus);
        }
        
        // 更新风控模态窗口
        if (typeof updateRiskModal === 'function') {
            updateRiskModal(this.riskStatus);
        }
        
        // 渲染风险等级历史趋势图
        if (typeof renderRiskTrendChart === 'function') {
            renderRiskTrendChart(this.riskHistory);
        }
        
        // 绑定事件
        this.bindEvents();
        
        // 加载市场温度数据（如果存在相关函数）
        if (typeof loadMarketTemperature === 'function') {
            await loadMarketTemperature();
        }
    }

    /**
     * 加载风控状态
     */
    async loadRiskStatus(forceRefresh = false) {
        try {
            const params = new URLSearchParams();
            if (forceRefresh) {
                params.append('force_refresh', 'true');
            }
            
            const response = await fetch(`/api/risk/status?${params}`);
            const result = await response.json();
            
            if (result.success) {
                this.riskStatus = result.data;
                console.log('风控状态加载成功:', this.riskStatus);
                
                // 更新UI
                this.updateRiskStatusUI();
            } else {
                console.error('加载风控状态失败:', result.message);
                this.showError('加载风控状态失败: ' + result.message);
            }
        } catch (error) {
            console.error('加载风控状态异常:', error);
            this.showError('加载风控状态异常: ' + error.message);
        }
    }

    /**
     * 加载风控历史
     */
    async loadRiskHistory(days = 30) {
        try {
            const response = await fetch(`/api/risk/history?days=${days}`);
            const result = await response.json();
            
            if (result.success) {
                this.riskHistory = result.data;
                console.log('风控历史加载成功:', this.riskHistory.length, '条记录');
                
                // 更新图表
                this.renderRiskHistoryChart();
            } else {
                console.error('加载风控历史失败:', result.message);
            }
        } catch (error) {
            console.error('加载风控历史异常:', error);
        }
    }

    /**
     * 更新风控状态UI
     */
    updateRiskStatusUI() {
        if (!this.riskStatus) return;

        // 更新VaR值显示
        const var1dElement = document.getElementById('var-1d-value');
        const var5dElement = document.getElementById('var-5d-value');
        const es1dElement = document.getElementById('es-1d-value');
        
        if (var1dElement) {
            var1dElement.textContent = `${(this.riskStatus.var_1d * 100).toFixed(2)}%`;
            var1dElement.className = this.getVarClass(this.riskStatus.var_1d);
        }
        
        if (var5dElement) {
            var5dElement.textContent = `${(this.riskStatus.var_5d * 100).toFixed(2)}%`;
            var5dElement.className = this.getVarClass(this.riskStatus.var_5d);
        }
        
        if (es1dElement) {
            es1dElement.textContent = `${(this.riskStatus.es_1d * 100).toFixed(2)}%`;
            es1dElement.className = this.getVarClass(this.riskStatus.es_1d);
        }

        // 更新风险等级显示
        const riskLevelElement = document.getElementById('risk-level');
        if (riskLevelElement) {
            riskLevelElement.textContent = this.riskStatus.risk_level;
            riskLevelElement.className = `risk-level ${this.getRiskLevelClass(this.riskStatus.risk_level)}`;
        }

        // 更新风控参数显示
        const positionLimitElement = document.getElementById('position-limit');
        const stopLossMultiplierElement = document.getElementById('stop-loss-multiplier');
        const scoreExtraElement = document.getElementById('score-extra');
        
        if (positionLimitElement) {
            positionLimitElement.textContent = `${(this.riskStatus.position_limit * 100).toFixed(0)}%`;
        }
        
        if (stopLossMultiplierElement) {
            stopLossMultiplierElement.textContent = this.riskStatus.stop_loss_multiplier.toFixed(1);
        }
        
        if (scoreExtraElement) {
            scoreExtraElement.textContent = this.riskStatus.score_extra;
        }

        // 更新策略启用状态
        const strategyEnabledElement = document.getElementById('strategy-enabled');
        if (strategyEnabledElement) {
            strategyEnabledElement.textContent = this.riskStatus.strategy_enabled ? '启用' : '禁用';
            strategyEnabledElement.className = `strategy-status ${this.riskStatus.strategy_enabled ? 'enabled' : 'disabled'}`;
        }

        // 更新日期显示
        const dateElement = document.getElementById('risk-date');
        if (dateElement) {
            dateElement.textContent = this.riskStatus.date;
        }
    }

    /**
     * 渲染风控状态卡片
     */
    renderRiskStatusCard() {
        const container = document.getElementById('risk-status-card');
        if (!container) {
            console.warn('未找到风控状态卡片容器');
            return;
        }

        const html = `
            <div class="card mb-4">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="card-title mb-0">风控状态</h5>
                    <div>
                        <button class="btn btn-sm btn-outline-primary" onclick="window.riskModule.refreshRiskStatus()">
                            <i class="fas fa-sync-alt"></i> 刷新
                        </button>
                    </div>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6>风险指标</h6>
                            <table class="table table-sm">
                                <tr>
                                    <td>日期:</td>
                                    <td id="risk-date">-</td>
                                </tr>
                                <tr>
                                    <td>风险等级:</td>
                                    <td><span id="risk-level" class="risk-level">-</span></td>
                                </tr>
                                <tr>
                                    <td>VaR(1日):</td>
                                    <td id="var-1d-value">-</td>
                                </tr>
                                <tr>
                                    <td>VaR(5日):</td>
                                    <td id="var-5d-value">-</td>
                                </tr>
                                <tr>
                                    <td>ES(1日):</td>
                                    <td id="es-1d-value">-</td>
                                </tr>
                            </table>
                        </div>
                        <div class="col-md-6">
                            <h6>风控参数</h6>
                            <table class="table table-sm">
                                <tr>
                                    <td>仓位上限:</td>
                                    <td id="position-limit">-</td>
                                </tr>
                                <tr>
                                    <td>止损倍数:</td>
                                    <td id="stop-loss-multiplier">-</td>
                                </tr>
                                <tr>
                                    <td>额外分数:</td>
                                    <td id="score-extra">-</td>
                                </tr>
                                <tr>
                                    <td>策略状态:</td>
                                    <td><span id="strategy-enabled" class="strategy-status">-</span></td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="card mb-4">
                <div class="card-header">
                    <h5 class="card-title mb-0">风险等级历史趋势</h5>
                </div>
                <div class="card-body">
                    <canvas id="risk-history-chart"></canvas>
                </div>
            </div>
        `;

        container.innerHTML = html;
    }

    /**
     * 渲染风险等级历史趋势图
     */
    renderRiskHistoryChart() {
        const canvas = document.getElementById('risk-history-chart');
        if (!canvas) return;

        // 准备数据
        const labels = this.riskHistory.map(item => item.date);
        const var1dData = this.riskHistory.map(item => (item.var_1d * 100).toFixed(2));
        const var5dData = this.riskHistory.map(item => (item.var_5d * 100).toFixed(2));

        // 销毁旧图表
        if (this.riskChart) {
            this.riskChart.destroy();
        }

        // 创建新图表
        const ctx = canvas.getContext('2d');
        this.riskChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'VaR(1日)',
                        data: var1dData,
                        borderColor: 'rgb(75, 192, 192)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        tension: 0.1
                    },
                    {
                        label: 'VaR(5日)',
                        data: var5dData,
                        borderColor: 'rgb(255, 99, 132)',
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: false,
                        title: {
                            display: true,
                            text: 'VaR (%)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: '日期'
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    }
                }
            }
        });
    }

    /**
     * 绑定事件
     */
    bindEvents() {
        // 刷新按钮事件已在HTML中绑定
    }

    /**
     * 刷新风控状态
     */
    async refreshRiskStatus() {
        console.log('刷新风控状态');
        await this.loadRiskStatus(true);
    }

    /**
     * 获取VaR值的CSS类
     */
    getVarClass(varValue) {
        const varPercent = varValue * 100;
        
        if (varPercent > -2) {
            return 'var-value var-normal';
        } else if (varPercent > -4) {
            return 'var-value var-caution';
        } else if (varPercent > -6) {
            return 'var-value var-danger';
        } else {
            return 'var-value var-crash';
        }
    }

    /**
     * 获取风险等级的CSS类
     */
    getRiskLevelClass(riskLevel) {
        const levelMap = {
            '正常': 'risk-normal',
            '注意': 'risk-caution',
            '危险': 'risk-danger',
            '崩溃': 'risk-crash'
        };
        return levelMap[riskLevel] || 'risk-normal';
    }

    /**
     * 显示错误信息
     */
    showError(message) {
        console.error(message);
        // 可以添加Toast通知
    }

    /**
     * 显示信息
     */
    showInfo(message) {
        console.info(message);
        // 可以添加Toast通知
    }
}

// 创建全局实例
const riskModule = new RiskModule();
window.riskModule = riskModule;

// 导出初始化函数供app.js调用
export async function initRiskModule() {
    await riskModule.init();
}