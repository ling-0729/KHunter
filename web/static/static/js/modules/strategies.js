/**
 * 策略配置相关功能模块
 */

// 全局变量：当前选中的策略
let currentStrategy = null;
let strategiesData = [];

/**
 * 加载策略列表 - 获取策略卡片列表和详情
 */
export async function loadStrategies() {
    try {
        // 获取策略列表
        const response = await fetch('/api/strategies');
        const result = await response.json();
        
        if (result.success) {
            strategiesData = result.data;
            renderStrategiesGrid(result.data);
        } else {
            document.getElementById('strategies-grid').innerHTML = 
                '<p class="placeholder">加载策略失败: ' + result.error + '</p>';
        }
    } catch (error) {
        console.error('加载策略失败:', error);
        document.getElementById('strategies-grid').innerHTML = 
            '<p class="placeholder">加载策略失败: ' + error.message + '</p>';
    }
}

/**
 * 渲染策略卡片网格
 * @param {Array} strategies - 策略列表
 */
export function renderStrategiesGrid(strategies) {
    const grid = document.getElementById('strategies-grid');
    
    if (!strategies || strategies.length === 0) {
        grid.innerHTML = '<p class="placeholder">暂无策略</p>';
        return;
    }
    
    // 生成策略卡片
    grid.innerHTML = strategies.map(strategy => `
        <div class="strategy-card" onclick="viewStrategyDetail('${strategy.name}')">
            <div class="strategy-card-icon">${strategy.icon || '📊'}</div>
            <div class="strategy-card-name">${strategy.display_name}</div>
            <div class="strategy-card-description">${strategy.description}</div>
            <div class="strategy-card-footer">
                <div class="strategy-card-params">${Object.keys(strategy.params || {}).length} 个参数</div>
                <div class="strategy-card-arrow">→</div>
            </div>
        </div>
    `).join('');
}

/**
 * 查看策略详情
 * @param {string} strategyName - 策略名称
 */
export async function viewStrategyDetail(strategyName) {
    try {
        // 获取策略详情
        const response = await fetch(`/api/strategies/${strategyName}`);
        const result = await response.json();
        
        if (result.success) {
            currentStrategy = result.data;
            renderStrategyDetail(result.data);
            
            // 切换到详情视图
            document.getElementById('strategies-list-view').style.display = 'none';
            document.getElementById('strategies-detail-view').style.display = 'block';
        } else {
            alert('加载策略详情失败: ' + result.error);
        }
    } catch (error) {
        console.error('加载策略详情失败:', error);
        alert('加载策略详情失败: ' + error.message);
    }
}

/**
 * 渲染策略详情
 * @param {Object} detail - 策略详情
 */
export function renderStrategyDetail(detail) {
    // 设置基本信息
    document.getElementById('detail-icon').textContent = detail.icon || '📊';
    document.getElementById('detail-name').textContent = detail.display_name;
    document.getElementById('detail-description').textContent = detail.description;
    document.getElementById('detail-principle').textContent = detail.principle;
    
    // 设置颜色指示器
    const colorIndicator = document.getElementById('detail-color');
    colorIndicator.style.backgroundColor = detail.color || '#2563eb';
    
    // 渲染参数表单
    renderStrategyParamsForm(detail);
}

/**
 * 渲染参数表单
 * @param {Object} detail - 策略详情
 */
export function renderStrategyParamsForm(detail) {
    const formContainer = document.getElementById('strategy-params-form');
    const paramGroups = detail.param_groups || [];
    const paramDetails = detail.param_details || {};
    const currentParams = detail.current_params || {};
    
    if (Object.keys(paramDetails).length === 0) {
        formContainer.innerHTML = '<p class="text-muted">该策略无可配置参数</p>';
        return;
    }
    
    // 按分组渲染参数
    let html = '';
    
    paramGroups.forEach(group => {
        // 获取该分组下的参数
        const groupParams = Object.entries(paramDetails).filter(
            ([_, param]) => param.group === group.name
        );
        
        if (groupParams.length === 0) return;
        
        html += `
            <div class="param-group">
                <div class="param-group-title">
                    <span>📋</span> ${group.name}
                </div>
                <div class="param-group-description">${group.description}</div>
        `;
        
        // 渲染该分组下的参数
        groupParams.forEach(([paramName, paramDef]) => {
            const currentValue = currentParams[paramName] !== undefined ? 
                currentParams[paramName] : paramDef.default;
            const minVal = paramDef.min !== undefined ? paramDef.min : '';
            const maxVal = paramDef.max !== undefined ? paramDef.max : '';
            const rangeText = minVal !== '' && maxVal !== '' ? 
                `${minVal} ~ ${maxVal}` : '';
            
            html += `
                <div class="param-item">
                    <div class="param-label">
                        <span class="param-label-text">${paramDef.display_name}</span>
                        <span class="param-label-default">默认: ${paramDef.default}</span>
                    </div>
                    <div class="param-input-wrapper">
                        <input type="text" class="param-input" 
                               id="param-${paramName}" 
                               value="${currentValue}"
                               data-param-name="${paramName}"
                               data-param-type="${paramDef.type}"
                               data-param-min="${minVal}"
                               data-param-max="${maxVal}"
                               onchange="validateParamInput(this)">
                        ${rangeText ? `<span class="param-range">${rangeText}</span>` : ''}
                        <button class="param-reset-btn" onclick="resetParamToDefault('${paramName}', ${paramDef.default})">
                            重置
                        </button>
                    </div>
                    <div class="param-description">${paramDef.description}</div>
                    <div class="param-error" id="error-${paramName}"></div>
                </div>
            `;
        });
        
        html += '</div>';
    });
    
    formContainer.innerHTML = html;
}

/**
 * 验证参数输入
 * @param {HTMLInputElement} input - 输入元素
 * @returns {boolean} 验证结果
 */
export function validateParamInput(input) {
    const paramName = input.dataset.paramName;
    const paramType = input.dataset.paramType;
    const minVal = parseFloat(input.dataset.paramMin);
    const maxVal = parseFloat(input.dataset.paramMax);
    const errorDiv = document.getElementById(`error-${paramName}`);
    
    // 清除之前的错误
    errorDiv.textContent = '';
    
    // 类型检查
    let value = input.value;
    try {
        if (paramType === 'int') {
            value = parseInt(value);
        } else if (paramType === 'float') {
            value = parseFloat(value);
        }
    } catch (e) {
        errorDiv.textContent = `参数类型错误，应为${paramType}`;
        return false;
    }
    
    // 范围检查
    if (!isNaN(minVal) && value < minVal) {
        errorDiv.textContent = `参数值不能小于${minVal}`;
        return false;
    }
    if (!isNaN(maxVal) && value > maxVal) {
        errorDiv.textContent = `参数值不能大于${maxVal}`;
        return false;
    }
    
    return true;
}

/**
 * 重置参数到默认值
 * @param {string} paramName - 参数名称
 * @param {*} defaultValue - 默认值
 */
export function resetParamToDefault(paramName, defaultValue) {
    const input = document.getElementById(`param-${paramName}`);
    if (input) {
        input.value = defaultValue;
        validateParamInput(input);
    }
}

/**
 * 保存策略参数
 */
export async function saveStrategyParams() {
    if (!currentStrategy) return;
    
    // 收集所有参数值
    const params = {};
    const paramDetails = currentStrategy.param_details || {};
    
    let hasError = false;
    Object.keys(paramDetails).forEach(paramName => {
        const input = document.getElementById(`param-${paramName}`);
        if (input) {
            // 验证参数
            if (!validateParamInput(input)) {
                hasError = true;
                return;
            }
            params[paramName] = input.value;
        }
    });
    
    if (hasError) {
        alert('参数验证失败，请检查错误信息');
        return;
    }
    
    try {
        // 第一步：后端验证参数
        const validateResponse = await fetch(`/api/strategies/${currentStrategy.name}/validate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        const validateResult = await validateResponse.json();
        
        if (!validateResult.success) {
            // 显示验证错误
            const errors = validateResult.errors || {};
            Object.entries(errors).forEach(([paramName, error]) => {
                const errorDiv = document.getElementById(`error-${paramName}`);
                if (errorDiv) {
                    errorDiv.textContent = error;
                }
            });
            alert('参数验证失败，请检查错误信息');
            return;
        }
        
        // 第二步：保存参数到后端
        const saveResponse = await fetch(`/api/strategies/${currentStrategy.name}/params`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(params)
        });
        
        const saveResult = await saveResponse.json();
        
        if (saveResult.success) {
            alert('参数保存成功！');
            // 更新当前策略的参数
            currentStrategy.current_params = params;
        } else {
            alert('参数保存失败: ' + saveResult.error);
        }
    } catch (error) {
        console.error('保存参数失败:', error);
        alert('保存参数失败: ' + error.message);
    }
}

/**
 * 恢复策略参数到默认值
 */
export function resetStrategyParams() {
    if (!currentStrategy) return;
    
    if (confirm('确定要恢复所有参数到默认值吗？')) {
        const paramDetails = currentStrategy.param_details || {};
        Object.entries(paramDetails).forEach(([paramName, paramDef]) => {
            const input = document.getElementById(`param-${paramName}`);
            if (input) {
                input.value = paramDef.default;
                validateParamInput(input);
            }
        });
    }
}

/**
 * 返回策略列表
 */
export function backToStrategyList() {
    currentStrategy = null;
    document.getElementById('strategies-list-view').style.display = 'block';
    document.getElementById('strategies-detail-view').style.display = 'none';
}
