# -*- coding: utf-8 -*-
"""巨潮公告抓取（**全市场·按日** ✓）—— 供 `EventCollector` 回填公告标题

设计要点（2026-09-25）：
  · 复用 `trading/reduce_plan_cache` 已验证的巨潮参数与容错经验 ✓
    （直连 POST、超时、限流识别、结构容错 ✓）
  · **只产出标题所需的三个字段** ✓：`stock_code / ann_date / title`
    （URL、分类、来源**不落库** ✓ → 规则演进无需重采 ✓）
  · **在线检查点** `guard_online_call` ✓：回测（离线）期间调用将直接失败 ✗
  · 分页拉取（pageSize 可配 ✓）+ 页数上限（防异常空转 ✓）+ `<em>` 标签清洗 ✓
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CNINFO_QUERY_URL = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
CNINFO_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'),
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
}
CNINFO_TIMEOUT = 15
_TAG_RE = re.compile(r'<[^>]+>')


def clean_title(raw: str) -> str:
    """清洗公告标题（去掉巨潮高亮 `<em>` 标签与多余空白 ✓）"""
    return _TAG_RE.sub('', str(raw or '')).replace('\u3000', ' ').strip()


def _ms_to_date(value) -> str:
    """巨潮毫秒时间戳 → YYYY-MM-DD"""
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime('%Y-%m-%d')
    except Exception:
        return ''


class CninfoAnnouncementFetcher:
    """巨潮**全市场按日**公告抓取（返回标题三字段 ✓）"""

    def __init__(self, page_size: int = 50, max_pages: int = 400,
                 timeout: int = CNINFO_TIMEOUT, session=None):
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        self.timeout = timeout
        self._session = session

    def _post(self, payload: Dict):
        import requests
        if self._session is not None:
            return self._session.post(CNINFO_QUERY_URL, headers=CNINFO_HEADERS,
                                      data=payload, timeout=self.timeout)
        return requests.post(CNINFO_QUERY_URL, headers=CNINFO_HEADERS,
                             data=payload, timeout=self.timeout)

    def fetch_day(self, date_str: str) -> List[Dict]:
        """抓取某日**全市场**公告标题 ✓

        Args:
            date_str: YYYY-MM-DD

        Returns:
            [{'stock_code','ann_date','title'}, ...]（去重 ✓）
        """
        from utils.online_guard import PURPOSE_UPDATE, guard_online_call
        # 【2026-09-25 契约 ✓】采集 = **数据更新**流程 → `purpose='update'` ✓（合法联网 ✓）
        #   并与"评分只读本地"✗ 明确区分：评分侧无此豁免 ✓
        guard_online_call(f'巨潮公告抓取 {date_str}', purpose=PURPOSE_UPDATE)

        day = str(date_str)[:10]
        rows: List[Dict] = []
        seen = set()
        for page in range(1, self.max_pages + 1):
            payload = {
                'pageNum': str(page), 'pageSize': str(self.page_size),
                'column': 'szse', 'tabName': 'fulltext', 'plate': '',
                'stock': '',                      # 空 = 全市场 ✓
                'searchkey': '', 'secid': '', 'category': '', 'trade': '',
                'seDate': f'{day}~{day}',         # 单日区间 ✓
                'sortName': '', 'sortType': '', 'isHLtitle': 'true',
            }
            try:
                resp = self._post(payload)
                if resp.status_code in (403, 429) or resp.status_code >= 500:
                    logger.warning('巨潮限流/异常 HTTP %s（%s 第 %s 页）',
                                   resp.status_code, day, page)
                    return rows
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning('巨潮公告抓取异常（%s 第 %s 页）: %s', day, page, e)
                return rows

            items = (data or {}).get('announcements')
            if not isinstance(items, list) or not items:
                break
            for it in items:
                code = str(it.get('secCode') or '').strip()[:6]
                title = clean_title(it.get('announcementTitle'))
                ann = _ms_to_date(it.get('announcementTime')) or day
                if not code or not title:
                    continue
                key = (code, ann, title)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({'stock_code': code, 'ann_date': ann, 'title': title})
            if len(items) < self.page_size:
                break                          # 最后一页 ✓
        logger.info('巨潮公告 %s：抓取 %d 条（%d 页）', day, len(rows),
                    min(page, self.max_pages))
        return rows
