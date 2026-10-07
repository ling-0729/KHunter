/**
 * 收藏夹页面模块
 * 加载收藏股票列表，支持查看详情和取消收藏
 */

// ★【2026-10-04 用户要求 ✓】**全站前端统一版本号** ✗→✓
//   从自身 URL 取出 `?v=NN` ✓（源头 = `index.html` 的 `app.js?v=NN` ✓）。
const V = new URL(import.meta.url).search;
const imp = (p) => import(p + V);

/**
 * 加载收藏列表
 */
export async function loadFavorites() {
    const container = document.getElementById('favorites-list');
    if (!container) return;

    container.innerHTML = '<p style="color: #999;">加载中...</p>';

    try {
        const response = await fetch('/api/stock/favorites');
        const result = await response.json();

        if (!result.success) {
            container.innerHTML = `<p style="color: #dc2626;">加载失败: ${result.error || ''}</p>`;
            return;
        }

        const favorites = result.data || [];
        if (favorites.length === 0) {
            container.innerHTML = '<p style="color: #999;">暂无收藏股票</p>';
            return;
        }

        // 渲染收藏表格
        let html = `
            <table class="favorites-table">
                <thead>
                    <tr>
                        <th>股票代码</th>
                        <th>股票名称</th>
                        <th>选股策略</th>
                        <th>选入日期</th>
                        <th>保存日期</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
        `;

        favorites.forEach(item => {
            const code = item.stock_code || '';
            const name = item.stock_name || '-';
            const strategy = item.strategy_name || '-';
            const selDate = item.selection_date || '-';
            const savedAt = (item.saved_at || '').replace('T', ' ').substring(0, 19);

            html += `
                <tr>
                    <td><span class="stock-link" onclick="openFavStockDetail('${code}')">${code}</span></td>
                    <td>${name}</td>
                    <td>${strategy}</td>
                    <td>${selDate}</td>
                    <td>${savedAt}</td>
                    <td><button class="remove-btn" onclick="removeFavorite('${code}')">取消收藏</button></td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (error) {
        console.error('加载收藏列表失败:', error);
        container.innerHTML = `<p style="color: #dc2626;">加载失败: ${error.message}</p>`;
    }
}

/**
 * 打开收藏股票详情（穿透到股票详情弹窗）
 * @param {string} code - 股票代码
 */
window.openFavStockDetail = function(code) {
    // 调用 stocks.js 中的 viewStockDetail
    imp('./stocks.js').then(module => module.viewStockDetail(code));
};

/**
 * 取消收藏
 * @param {string} code - 股票代码
 */
window.removeFavorite = async function(code) {
    if (!confirm(`确定取消收藏 ${code} 吗？`)) return;

    try {
        const response = await fetch(`/api/stock/favorite/${code}`, { method: 'DELETE' });
        const result = await response.json();
        if (result.success) {
            // 重新加载列表
            loadFavorites();
        } else {
            alert('取消收藏失败: ' + (result.error || ''));
        }
    } catch (error) {
        alert('取消收藏失败: ' + error.message);
    }
};
