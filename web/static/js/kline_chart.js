/**
 * K线图表模块 - 使用Canvas绘制
 * 功能：显示K线图表、成交量和KDJ指标
 */

// 全局变量存储图表实例
let klineChartInstance = null;

/**
 * 初始化K线图表
 * @param {string} containerId - 容器ID
 * @param {Array} rawData - 原始数据数组
 */
function initKlineChart(containerId, rawData) {
    // 销毁旧的图表实例
    if (klineChartInstance) {
        klineChartInstance = null;
    }
    
    // 获取容器
    const container = document.getElementById(containerId);
    if (!container) {
        console.error(`容器 ${containerId} 不存在`);
        return;
    }
    
    // 清空容器
    container.innerHTML = '';
    
    // 检查容器尺寸
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;
    console.log(`容器尺寸: ${containerWidth}x${containerHeight}`);
    
    if (containerWidth === 0 || containerHeight === 0) {
        console.error(`容器尺寸无效: ${containerWidth}x${containerHeight}，容器可能未显示`);
        container.innerHTML = '<div style="padding: 20px; color: #ef4444;">容器尺寸无效，请稍后重试</div>';
        return;
    }
    
    try {
        // 转换数据格式
        const formattedData = formatKlineData(rawData);
        console.log(`K线数据点数: ${formattedData.candleData.length}`);
        
        // 检查是否有足够的数据
        if (formattedData.candleData.length === 0) {
            console.error('没有有效的K线数据');
            container.innerHTML = '<div style="padding: 20px; color: #ef4444;">没有有效的K线数据</div>';
            return;
        }
        
        // 创建Canvas元素
        const canvas = document.createElement('canvas');
        
        // 设置Canvas的显示尺寸（CSS像素）
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.display = 'block';
        
        // 设置Canvas的绘制尺寸（逻辑像素）
        canvas.width = containerWidth;
        canvas.height = containerHeight;
        
        container.appendChild(canvas);
        
        // 获取绘图上下文
        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) {
            throw new Error('无法获取Canvas上下文');
        }
        
        // 绘制K线图表
        drawKlineChart(ctx, canvas, formattedData, rawData);
        
        // 保存图表实例
        klineChartInstance = { canvas, ctx };
        
        console.log('K线图表初始化成功');
        
    } catch (error) {
        console.error('K线图表初始化失败:', error);
        container.innerHTML = `<div style="padding: 20px; color: #ef4444;">图表初始化失败: ${error.message}</div>`;
    }
}

/**
 * 绘制移动平均线
 * @param {CanvasRenderingContext2D} ctx - Canvas上下文
 * @param {Object} formattedData - 格式化的数据
 * @param {number} padding - 内边距
 * @param {number} chartHeight - 图表高度
 * @param {number} adjustedMin - 调整后的最小价格
 * @param {number} adjustedRange - 调整后的价格范围
 * @param {number} candleSpacing - K线间距
 */
function drawMovingAverages(ctx, formattedData, padding, chartHeight, adjustedMin, adjustedRange, candleSpacing) {
    // 定义均线配置（只保留MA5和MA10）
    const maConfigs = [
        { data: formattedData.ma5Data, color: '#2962FF', label: 'MA5', lineWidth: 1.5 },
        { data: formattedData.ma10Data, color: '#FF6D00', label: 'MA10', lineWidth: 1.5 }
    ];
    
    // 计算Y坐标的辅助函数
    const getY = (price) => {
        return padding + chartHeight - ((price - adjustedMin) / adjustedRange) * chartHeight;
    };
    
    // 绘制每条均线
    maConfigs.forEach(config => {
        if (!config.data || config.data.length === 0) return;
        
        ctx.strokeStyle = config.color;
        ctx.lineWidth = config.lineWidth;
        ctx.beginPath();
        
        let isFirstPoint = true;
        
        // 使用candleData的索引来正确对应均线数据
        formattedData.candleData.forEach((candle, candleIndex) => {
            // 查找对应的均线数据点
            const maPoint = config.data.find(p => p.time === candle.time);
            
            if (maPoint) {
                const x = padding + candleIndex * candleSpacing + candleSpacing / 2;
                const y = getY(maPoint.value);
                
                if (isFirstPoint) {
                    ctx.moveTo(x, y);
                    isFirstPoint = false;
                } else {
                    ctx.lineTo(x, y);
                }
            }
        });
        
        ctx.stroke();
    });
    
    // 绘制均线图例
    drawMALegend(ctx, maConfigs, padding);
}

/**
 * 绘制均线图例
 * @param {CanvasRenderingContext2D} ctx - Canvas上下文
 * @param {Array} maConfigs - 均线配置数组
 * @param {number} padding - 内边距
 */
function drawMALegend(ctx, maConfigs, padding) {
    const legendX = padding + 20;
    const legendY = padding + 20;
    const lineHeight = 18;
    
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    ctx.textAlign = 'left';
    
    maConfigs.forEach((config, index) => {
        if (!config.data || config.data.length === 0) return;
        
        const y = legendY + index * lineHeight;
        
        // 绘制颜色块
        ctx.fillStyle = config.color;
        ctx.fillRect(legendX, y - 8, 12, 2);
        
        // 绘制标签
        ctx.fillStyle = config.color;
        ctx.fillText(config.label, legendX + 18, y);
    });
}

/**
 * 绘制K线图表
 * @param {CanvasRenderingContext2D} ctx - Canvas上下文
 * @param {HTMLCanvasElement} canvas - Canvas元素
 * @param {Object} formattedData - 格式化的数据
 * @param {Array} rawData - 原始数据
 */
function drawKlineChart(ctx, canvas, formattedData, rawData) {
    // 获取设备像素比，用于高清显示
    const dpr = window.devicePixelRatio || 1;
    const displayWidth = canvas.width;
    const displayHeight = canvas.height;
    
    // 设置Canvas的实际绘制尺寸（高清）
    canvas.width = displayWidth * dpr;
    canvas.height = displayHeight * dpr;
    
    // 缩放上下文以适应高清显示
    ctx.scale(dpr, dpr);
    
    // 使用显示尺寸进行计算
    const width = displayWidth;
    const height = displayHeight;
    const padding = 60;
    const chartWidth = width - padding * 2;
    
    // 为成交量图表留出空间，K线图占65%，成交量图占35%
    const klineHeight = (height - padding * 2) * 0.65;
    const volumeHeight = (height - padding * 2) * 0.35;
    const volumeStartY = padding + klineHeight;
    
    // 清空画布
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
    
    // 启用文字抗锯齿
    ctx.textRendering = 'optimizeLegibility';
    ctx.imageSmoothingEnabled = true;
    
    // 获取价格范围
    const prices = formattedData.candleData.map(d => [d.high, d.low]).flat();
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice || 1;
    
    // 添加价格范围的上下边距
    const paddingPercent = 0.1;
    const adjustedMin = minPrice - priceRange * paddingPercent;
    const adjustedMax = maxPrice + priceRange * paddingPercent;
    const adjustedRange = adjustedMax - adjustedMin;
    
    // 计算K线宽度
    const candleWidth = Math.max(3, Math.floor(chartWidth / formattedData.candleData.length * 0.6));
    const candleSpacing = Math.floor(chartWidth / formattedData.candleData.length);
    
    // 绘制背景网格
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 0.5;
    
    // 水平网格线和价格标签
    for (let i = 0; i <= 5; i++) {
        const y = padding + (klineHeight / 5) * i;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
        
        // 绘制价格标签
        const price = adjustedMax - (adjustedRange / 5) * i;
        ctx.fillStyle = '#666';
        ctx.font = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(price.toFixed(2), padding - 15, y + 4);
    }
    
    // 绘制竖直网格线和日期标签
    const gridLines = Math.min(10, Math.floor(formattedData.candleData.length / 5));
    for (let i = 0; i <= gridLines; i++) {
        const x = padding + (chartWidth / gridLines) * i;
        ctx.beginPath();
        ctx.moveTo(x, padding);
        ctx.lineTo(x, height - padding);
        ctx.stroke();
        
        // 绘制日期标签 - 使用formattedData.candleData中的数据
        const dataIndex = Math.floor((formattedData.candleData.length - 1) * (i / gridLines));
        if (dataIndex >= 0 && dataIndex < formattedData.candleData.length) {
            // 从formattedData中获取日期，而不是rawData
            // formattedData.candleData已经是正确顺序的（从早到晚）
            const candle = formattedData.candleData[dataIndex];
            
            // 从rawData中查找对应的日期
            let date = '';
            for (let j = 0; j < rawData.length; j++) {
                const rawDate = new Date(rawData[j].date);
                const candleDate = new Date(candle.time * 1000);
                
                // 比较日期是否相同
                if (rawDate.toDateString() === candleDate.toDateString()) {
                    date = rawData[j].date;
                    break;
                }
            }
            
            if (date) {
                ctx.fillStyle = '#666';
                ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(date, x, height - padding + 20);
            }
        }
    }
    
    // 绘制K线
    formattedData.candleData.forEach((item, index) => {
        const x = padding + index * candleSpacing + candleSpacing / 2;
        
        // 计算Y坐标
        const getY = (price) => {
            return padding + klineHeight - ((price - adjustedMin) / adjustedRange) * klineHeight;
        };
        
        const openY = getY(item.open);
        const closeY = getY(item.close);
        const highY = getY(item.high);
        const lowY = getY(item.low);
        
        // 判断涨跌
        const isUp = item.close >= item.open;
        const color = isUp ? '#ef4444' : '#10b981';
        
        // 绘制影线（高低价）
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, highY);
        ctx.lineTo(x, lowY);
        ctx.stroke();
        
        // 绘制K线实体
        ctx.fillStyle = color;
        const bodyTop = Math.min(openY, closeY);
        const bodyHeight = Math.abs(closeY - openY) || 2;
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
    });
    
    // 绘制均线
    drawMovingAverages(ctx, formattedData, padding, klineHeight, adjustedMin, adjustedRange, candleSpacing);
    
    // 绘制成交量图表
    drawVolumeChart(ctx, formattedData, padding, volumeStartY, volumeHeight, candleWidth, candleSpacing);
    
    // 绘制坐标轴
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.stroke();
    
    // 绘制K线图和成交量图的分隔线
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding, volumeStartY);
    ctx.lineTo(width - padding, volumeStartY);
    ctx.stroke();
    
    // 绘制Y轴标签
    ctx.fillStyle = '#666';
    ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.save();
    ctx.translate(15, padding + klineHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('价格 (¥)', 0, 0);
    ctx.restore();
    
    // 绘制成交量Y轴标签
    ctx.save();
    ctx.translate(15, volumeStartY + volumeHeight / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('成交量', 0, 0);
    ctx.restore();
    
    // 绘制X轴标签
    ctx.fillStyle = '#666';
    ctx.font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('交易日期', width / 2, height - 10);
    
    // 绘制标题
    ctx.fillStyle = '#1f2937';
    ctx.font = 'bold 16px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('K线图表', padding + 10, padding - 20);
    
    // 添加图例
    addChartLegend(canvas.parentElement, rawData);
}

/**
 * 绘制成交量图表
 * @param {CanvasRenderingContext2D} ctx - Canvas上下文
 * @param {Object} formattedData - 格式化的数据
 * @param {number} padding - 内边距
 * @param {number} volumeStartY - 成交量图表起始Y坐标
 * @param {number} volumeHeight - 成交量图表高度
 * @param {number} candleWidth - K线宽度
 * @param {number} candleSpacing - K线间距
 */
function drawVolumeChart(ctx, formattedData, padding, volumeStartY, volumeHeight, candleWidth, candleSpacing) {
    // 获取成交量范围
    const volumes = formattedData.volumeData.map(d => d.value);
    const maxVolume = volumes.length > 0 ? Math.max(...volumes) : 1;
    
    // 绘制成交量柱状图
    formattedData.volumeData.forEach((item, index) => {
        const x = padding + index * candleSpacing + candleSpacing / 2;
        
        // 计算Y坐标
        const volumeY = volumeStartY + volumeHeight - (item.value / maxVolume) * volumeHeight;
        const volumeBarHeight = volumeHeight - (volumeY - volumeStartY);
        
        // 绘制成交量柱状图
        ctx.fillStyle = item.color;
        ctx.fillRect(x - candleWidth / 2, volumeY, candleWidth, volumeBarHeight);
    });
    
    // 绘制成交量网格线
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 0.5;
    
    for (let i = 1; i <= 3; i++) {
        const y = volumeStartY + (volumeHeight / 3) * i;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        // 使用与K线相同的长度来计算网格线宽度，确保对齐
        ctx.lineTo(padding + (candleSpacing * formattedData.candleData.length), y);
        ctx.stroke();
    }
}

/**
 * 计算简单移动平均线（SMA）
 * @param {Array} prices - 价格数组
 * @param {number} period - 周期（如5、10、20）
 * @returns {Array} 均线数据
 */
function calculateSMA(prices, period) {
    const sma = [];
    for (let i = 0; i < prices.length; i++) {
        if (i < period - 1) {
            sma.push(null);
        } else {
            let sum = 0;
            for (let j = i - period + 1; j <= i; j++) {
                sum += prices[j];
            }
            sma.push(sum / period);
        }
    }
    return sma;
}

/**
 * 转换数据格式为TradingView格式
 * @param {Array} rawData - 原始数据数组
 * @returns {Object} 转换后的数据对象
 */
function formatKlineData(rawData) {
    // 不再反转数据，因为API现在返回的是按日期升序排列的数据（最早的在前，最新的在后）
    const candleData = [];
    const volumeData = [];
    const kData = [];
    const dData = [];
    const jData = [];
    const closePrices = [];
    
    // 遍历数据并转换格式
    rawData.forEach((item) => {
        // 转换日期为时间戳（秒）
        const date = new Date(item.date);
        const time = Math.floor(date.getTime() / 1000);
        
        // 只有当K线数据完整时，才添加所有数据
        if (item.open && item.high && item.low && item.close) {
            // K线数据
            candleData.push({
                time: time,
                open: item.open,
                high: item.high,
                low: item.low,
                close: item.close
            });
            closePrices.push(item.close);
            
            // 成交量数据
            const volumeValue = item.volume || 0;
            // 根据收盘价与开盘价判断颜色
            const color = item.close >= item.open ? '#ef4444' : '#10b981';
            volumeData.push({
                time: time,
                value: volumeValue,
                color: color
            });
            
            // KDJ指标数据
            if (item.K !== null && item.K !== undefined) {
                kData.push({
                    time: time,
                    value: item.K
                });
            }
            
            if (item.D !== null && item.D !== undefined) {
                dData.push({
                    time: time,
                    value: item.D
                });
            }
            
            if (item.J !== null && item.J !== undefined) {
                jData.push({
                    time: time,
                    value: item.J
                });
            }
        }
    });
    
    // 计算均线（只保留MA5和MA10）
    const ma5 = calculateSMA(closePrices, 5);
    const ma10 = calculateSMA(closePrices, 10);
    
    // 转换均线数据格式
    const ma5Data = [];
    const ma10Data = [];
    
    candleData.forEach((candle, index) => {
        if (ma5[index] !== null) {
            ma5Data.push({
                time: candle.time,
                value: ma5[index]
            });
        }
        if (ma10[index] !== null) {
            ma10Data.push({
                time: candle.time,
                value: ma10[index]
            });
        }
    });
    
    return {
        candleData,
        volumeData,
        kData,
        dData,
        jData,
        ma5Data,
        ma10Data
    };
}

/**
 * 添加图表图例
 * @param {HTMLElement} container - 容器元素
 * @param {Array} rawData - 原始数据
 */
function addChartLegend(container, rawData) {
    // 不显示图例，只显示K线图表
    // 图例已被移除，用户只需要看到清晰的K线图表
}

/**
 * 格式化成交量显示
 * @param {number} volume - 成交量
 * @returns {string} 格式化后的成交量
 */
function formatVolume(volume) {
    if (volume >= 1e8) {
        return (volume / 1e8).toFixed(2) + '亿';
    } else if (volume >= 1e4) {
        return (volume / 1e4).toFixed(2) + '万';
    } else {
        return volume.toString();
    }
}

/**
 * 销毁K线图表
 */
function destroyKlineChart() {
    if (klineChartInstance) {
        klineChartInstance.remove();
        klineChartInstance = null;
    }
}
