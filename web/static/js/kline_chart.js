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
/**
 * 绘制九转(TD Sequential)标注（2026-09-20 新增）
 *   买入(下跌)序列：贴在该根 K 线**低点下方** → **红色数字**
 *   卖出(上升)序列：贴在该根 K 线**高点上方** → **绿色数字**
 *   样式（2026-09-20 调整）：**不使用圆点**，只显示加粗数字 + 白色光晕（描边），
 *   因此不受 K 线间距限制、也不会沿走势斜排压盖；
 *   序号 9（完成位）字号更大（**不加下划线** · 2026-09-20 按反馈去掉）；被取消的序列 → 灰色
 *   显示口径（2026-09-20）：完整 9 转 **或** "进行中且末端在最后一根 K 线、计数 >= 7"
 *   数据来源：后端 GET /api/stock/<code> 每根 K 线的 td9 字段（按日期挂载）
 * 数据来源：后端 GET /api/stock/<code> 每根 K 线的 td9 字段（按日期挂载）
 */
function drawTD9Marks(ctx, formattedData, padding, chartHeight, adjustedMin, adjustedRange, candleSpacing) {
    if (!formattedData || !formattedData.candleData || !formattedData.candleData.length) return;
    const getY = (price) => padding + chartHeight - ((price - adjustedMin) / adjustedRange) * chartHeight;
    // 【2026-09-20】按国内习惯：买入序列=红、卖出序列=绿（原为买绿卖红 ✗）
    const C_BUY = '#dc2626', C_SELL = '#16a34a', C_OFF = '#94a3b8';
    const narrow = candleSpacing < 7;          // K 线密集时字号略小
    const fs = narrow ? 11 : 12;               // 【2026-09-20】加大字号：只留数字也要醒目 ✓

    // 【2026-09-20】按类型扫描连续段（序号逐根 +1），满足以下**任一**条件即显示：
    //   ① 完整 9 转：本段序号走到 9 ✓
    //   ② **进行中**（2026-09-20 新增需求）：序列末端就在**最后一根 K 线**上，
    //      且当前计数 **>= 7** ✓ → 提前显示，便于预判"即将完成的九转"（不必等它到 9）
    //   其余碎片（中间位置断掉、或末端不足 7）一律不画 ✓
    const TYPES = ['buy_setup', 'buy_countdown', 'sell_setup', 'sell_countdown'];
    const completeKeys = new Set();            // `${index}|${type}` —— 需要显示的序号
    const lastIdx = formattedData.candleData.length - 1;
    TYPES.forEach(function (t) {
        let run = [];
        const flush = function () {
            if (run.length) {
                const tail = run[run.length - 1];
                const isComplete = tail.v >= 9;
                const isPendingOnLastBar = (tail.i === lastIdx && tail.v >= 7);
                if (isComplete || isPendingOnLastBar) {
                    run.forEach(function (r) { completeKeys.add(r.i + '|' + t); });
                }
            }
            run = [];
        };
        formattedData.candleData.forEach(function (c, i) {
            const v = c.td9 ? c.td9[t] : null;
            if (v === undefined || v === null) { flush(); return; }
            if (run.length && !(i === run[run.length - 1].i + 1
                    && v === run[run.length - 1].v + 1)) {
                flush();
            }
            run.push({ i: i, v: v });
        });
        flush();
    });

    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    let drawn = 0;                                  // 【2026-09-22】绘制计数，便于自检 ✓
    formattedData.candleData.forEach((candle, index) => {
        const td9 = candle.td9;
        if (!td9) return;
        const x = padding + index * candleSpacing + candleSpacing / 2;
        // 【2026-09-20】按要求**恢复"跟随 K 线"的原始位置**（此前的固定横排已回退 ✗）：
        //   买入序列 → 贴在该根 K 线**低点下方**（Setup 近、Countdown 再下一层）
        //   卖出序列 → 贴在该根 K 线**高点上方**
        //   由于现在只画数字（无圆点 ✓），不会再出现圆点互相压盖的问题 ✓
        const slots = [
            ['buy_setup', getY(candle.low) + 13, C_BUY, td9.buy_setup_cancelled],
            ['buy_countdown', getY(candle.low) + 28, C_BUY, td9.buy_countdown_cancelled],
            ['sell_setup', getY(candle.high) - 13, C_SELL, td9.sell_setup_cancelled],
            ['sell_countdown', getY(candle.high) - 28, C_SELL, td9.sell_countdown_cancelled]
        ];
        slots.forEach(([key, yRaw, color, cancelled]) => {
            const seq = td9[key];
            if (seq === undefined || seq === null) return;
            // 只画"完整 9 转"所属的序号（未完成序列不标注，见上方 completeKeys）
            if (!completeKeys.has(index + '|' + key)) return;
            // 【2026-09-22】把标注 Y 值**钳制在 K 线区内** ✗→✓：
            //   买点原本在低点下方 +13/+28px，若该 K 线贴近区间底部，数字会落进
            //   成交量区 ✗ → 被后绘制的成交量柱盖住 ✗（图上看不到标注的根因之一 ✓）
            const y = Math.min(padding + chartHeight - 8, Math.max(padding + 8, yRaw));
            // 【2026-09-20】去掉圆点，只显示"明显的数字"：
            //   ① 粗体 + 白色光晕（描边）→ 压在任何背景上都清晰 ✓
            //   ② 完成位（9）字号更大（不加下划线 ✓ 已按反馈去掉 ✗）
            const label = String(seq);
            const txtColor = cancelled ? C_OFF : color;
            ctx.globalAlpha = cancelled ? 0.65 : 1;
            ctx.font = 'bold ' + (seq >= 9 ? fs + 2 : fs)
                + 'px -apple-system, BlinkMacSystemFont, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.lineWidth = 3;
            ctx.strokeStyle = 'rgba(255,255,255,0.95)';   // 白色光晕
            ctx.strokeText(label, x, y);
            ctx.fillStyle = txtColor;
            ctx.fillText(label, x, y);
            ctx.globalAlpha = 1;
            drawn += 1;                         // 【2026-09-22】计入已绘制数 ✓
        });
    });
    ctx.restore();
    // 【2026-09-22】自检日志：若"数据有 9 转却看不到标注"，先看这里 ✓
    //   · drawn > 0 → 数据/逻辑正常（此前看不到是被成交量柱盖住 ✗，已修 ✓）
    //   · drawn = 0 → 该窗口内确实没有"完整 9 转 / 末端≥7 的进行中序列" ✓
    if (drawn > 0) {
        console.log('[九转] 已绘制 ' + drawn + ' 个序号标记');
    } else {
        console.warn('[九转] 本窗口无 9 转可标注（需"完整 9 转"，或"末端在最后一根且计数≥7"）');
    }
}

function drawMovingAverages(ctx, formattedData, padding, chartHeight, adjustedMin, adjustedRange, candleSpacing) {
    // 定义均线配置（MA5、MA10和MA20）
    const maConfigs = [
        { data: formattedData.ma5Data, color: '#2962FF', label: 'MA5', lineWidth: 1.5 },
        { data: formattedData.ma10Data, color: '#FF6D00', label: 'MA10', lineWidth: 1.5 },
        { data: formattedData.ma20Data, color: '#FFD700', label: 'MA20', lineWidth: 1.5 }
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
    // 【2026-09-20】图例布局：横向一行 + 移到"标题行"（绘图区**之外**）
    //   ① 原纵向堆叠（legendY + index*18）✗ → 标签彼此压盖 ✗
    //   ② 曾画在绘图区内（padding+8）✗ → 白色底把 K 线挡住了 ✗
    //   现：横向排列，位置在标题右侧（绘图区之上）→ 与 K 线零重叠 ✓，仍处左上角区域 ✓
    const items = maConfigs.filter(function (c) { return c.data && c.data.length; });
    if (!items.length) return;

    const font = 'bold 12px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    ctx.save();
    ctx.font = font;

    const swatchW = 16, swatchGap = 6, itemGap = 18, boxPadX = 10;
    let contentW = 0;
    items.forEach(function (c, i) {
        contentW += swatchW + swatchGap + ctx.measureText(c.label).width + (i ? itemGap : 0);
    });

    // 【2026-09-20】区域修正：图例移到**标题行**（K 线绘图区**之上**、紧接标题右侧）
    //   原实现画在 padding+8（绘图区内部）✗ → 白色底把 K 线挡住了 ✗；
    //   现在图例不再与 K 线重叠，仍处"左上角"区域 ✓
    ctx.font = 'bold 16px -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
    const titleW = ctx.measureText('K线图表').width;
    ctx.font = font;                          // ⚠️ 还原 12px 粗体：后续标签的测量与绘制都用它 ✓
    const boxX = padding + 10 + titleW + 24;
    const boxY = padding - 36;               // 与标题基线（padding-20）同一行
    const boxH = 24;
    const boxW = contentW + boxPadX * 2;

    // 圆角白底（避免与 K 线/网格互相干扰）
    const r = 7;
    ctx.beginPath();
    ctx.moveTo(boxX + r, boxY);
    ctx.lineTo(boxX + boxW - r, boxY);
    ctx.quadraticCurveTo(boxX + boxW, boxY, boxX + boxW, boxY + r);
    ctx.lineTo(boxX + boxW, boxY + boxH - r);
    ctx.quadraticCurveTo(boxX + boxW, boxY + boxH, boxX + boxW - r, boxY + boxH);
    ctx.lineTo(boxX + r, boxY + boxH);
    ctx.quadraticCurveTo(boxX, boxY + boxH, boxX, boxY + boxH - r);
    ctx.lineTo(boxX, boxY + r);
    ctx.quadraticCurveTo(boxX, boxY, boxX + r, boxY);
    ctx.closePath();
    ctx.fillStyle = 'rgba(255,255,255,0.92)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(148,163,184,0.55)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // 横向依次绘制：色条 + 名称
    let x = boxX + boxPadX;
    const cy = boxY + boxH / 2;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    items.forEach(function (c) {
        ctx.strokeStyle = c.color;
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(x, cy);
        ctx.lineTo(x + swatchW, cy);
        ctx.stroke();
        x += swatchW + swatchGap;
        ctx.fillStyle = c.color;
        ctx.fillText(c.label, x, cy);
        x += ctx.measureText(c.label).width + itemGap;
    });
    ctx.restore();
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

    // 【2026-09-22 修复】九转(TD)标注改到**最后**绘制（原来在成交量图之前 ✗）：
    //   买点序号画在 K 线低点下方 +13/+28px，一旦贴近 K 线区底部就会落进成交量区 ✗，
    //   而后绘制的成交量柱最高可占满整个成交量区 → 把数字**整段盖掉** ✗✓
    //   （这正是"数据/算法都对，但图上看不到标注"的原因 ✓）
    //   配合 drawTD9Marks 内部的 Y 值钳制，确保数字始终落在 K 线区内、且压在最上层 ✓
    drawTD9Marks(ctx, formattedData, padding, klineHeight, adjustedMin, adjustedRange, candleSpacing);
    
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
                close: item.close,
                // 九转(TD)标注：后端按日期挂好 {buy_setup,buy_countdown,sell_setup,sell_countdown,_cancelled}
                td9: item.td9 || null
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
    
    // 计算均线（计算MA5、MA10和MA20）
    const ma5 = calculateSMA(closePrices, 5);
    const ma10 = calculateSMA(closePrices, 10);
    const ma20 = calculateSMA(closePrices, 20);
    
    // 转换均线数据格式
    const ma5Data = [];
    const ma10Data = [];
    const ma20Data = [];
    
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
        if (ma20[index] !== null) {
            ma20Data.push({
                time: candle.time,
                value: ma20[index]
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
        ma10Data,
        ma20Data
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
