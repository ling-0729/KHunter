"""
测试选股结果手动保存功能

测试覆盖：
1. 单元测试：/api/save_selection 接口的各种场景
2. 集成测试：选股执行不再自动保存 + 手动保存流程
"""
import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client():
    """创建Flask测试客户端，mock掉selection_record_manager避免写真实数据库"""
    from web_server import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


# ========== 单元测试：/api/save_selection 接口 ==========

class TestSaveSelectionAPI:
    """测试手动保存选股结果API"""

    def test_save_selection_success(self, client):
        """测试正常保存 - 有效的选股数据"""
        # 构造模拟选股结果
        mock_results = {
            'morning_star': [
                {'code': '000001', 'name': '平安银行', 'signals': [{'close': 10.5}]},
                {'code': '000002', 'name': '万科A', 'signals': [{'close': 20.3}]}
            ]
        }
        # mock save_selection_result 返回成功
        mock_return = {'success': True, 'saved': 2, 'skipped': 0, 'updated': 0, 'error': 0}

        with patch('web_server.selection_record_manager') as mock_mgr:
            mock_mgr.save_selection_result.return_value = mock_return

            # 发送保存请求
            response = client.post('/api/save_selection',
                data=json.dumps({
                    'results': mock_results,
                    'time': '2026-03-24 10:30:00'
                }),
                content_type='application/json'
            )

            # 验证响应
            data = response.get_json()
            assert response.status_code == 200
            assert data['success'] is True
            assert data['saved'] == 2

            # 验证调用参数
            mock_mgr.save_selection_result.assert_called_once()
            call_args = mock_mgr.save_selection_result.call_args
            assert call_args.kwargs['strategy_names'] == ['morning_star']
            assert len(call_args.kwargs['signals']) == 2

    def test_save_selection_empty_results(self, client):
        """测试空结果 - 没有可保存的数据"""
        with patch('web_server.selection_record_manager'):
            response = client.post('/api/save_selection',
                data=json.dumps({'results': {}, 'time': '2026-03-24 10:30:00'}),
                content_type='application/json'
            )

            data = response.get_json()
            assert response.status_code == 200
            assert data['success'] is False
            assert '没有可保存' in data['error']

    def test_save_selection_skip_special_fields(self, client):
        """测试跳过特殊字段（_intersection_analysis等）"""
        mock_results = {
            '_intersection_analysis': {'total': 5},
            'bowl_rebound': [
                {'code': '600001', 'name': '邯郸钢铁', 'signals': []}
            ]
        }
        mock_return = {'success': True, 'saved': 1, 'skipped': 0, 'updated': 0, 'error': 0}

        with patch('web_server.selection_record_manager') as mock_mgr:
            mock_mgr.save_selection_result.return_value = mock_return

            response = client.post('/api/save_selection',
                data=json.dumps({'results': mock_results, 'time': '2026-03-24 10:30:00'}),
                content_type='application/json'
            )

            data = response.get_json()
            assert data['success'] is True
            # 只传入了 bowl_rebound，不包含 _intersection_analysis
            call_args = mock_mgr.save_selection_result.call_args
            assert '_intersection_analysis' not in call_args.kwargs['strategy_names']
            assert 'bowl_rebound' in call_args.kwargs['strategy_names']

    def test_save_selection_invalid_time(self, client):
        """测试无效时间格式 - 应回退到当前时间"""
        mock_results = {
            'morning_star': [
                {'code': '000001', 'name': '平安银行', 'signals': []}
            ]
        }
        mock_return = {'success': True, 'saved': 1, 'skipped': 0, 'updated': 0, 'error': 0}

        with patch('web_server.selection_record_manager') as mock_mgr:
            mock_mgr.save_selection_result.return_value = mock_return

            # 传入无效时间
            response = client.post('/api/save_selection',
                data=json.dumps({'results': mock_results, 'time': 'invalid-time'}),
                content_type='application/json'
            )

            data = response.get_json()
            # 即使时间无效也应该保存成功（回退到当前时间）
            assert data['success'] is True

    def test_save_selection_multi_strategy(self, client):
        """测试多策略结果保存"""
        mock_results = {
            'morning_star': [
                {'code': '000001', 'name': '平安银行', 'signals': []}
            ],
            'bowl_rebound': [
                {'code': '000002', 'name': '万科A', 'signals': []},
                {'code': '000003', 'name': '国农科技', 'signals': []}
            ]
        }
        mock_return = {'success': True, 'saved': 3, 'skipped': 0, 'updated': 0, 'error': 0}

        with patch('web_server.selection_record_manager') as mock_mgr:
            mock_mgr.save_selection_result.return_value = mock_return

            response = client.post('/api/save_selection',
                data=json.dumps({'results': mock_results, 'time': '2026-03-24 10:30:00'}),
                content_type='application/json'
            )

            data = response.get_json()
            assert data['success'] is True
            assert data['saved'] == 3
            # 验证策略名称包含两个策略
            call_args = mock_mgr.save_selection_result.call_args
            assert set(call_args.kwargs['strategy_names']) == {'morning_star', 'bowl_rebound'}
            assert len(call_args.kwargs['signals']) == 3

    def test_save_selection_exception(self, client):
        """测试保存过程中发生异常"""
        mock_results = {
            'morning_star': [
                {'code': '000001', 'name': '平安银行', 'signals': []}
            ]
        }

        with patch('web_server.selection_record_manager') as mock_mgr:
            # 模拟保存时抛出异常
            mock_mgr.save_selection_result.side_effect = Exception('数据库连接失败')

            response = client.post('/api/save_selection',
                data=json.dumps({'results': mock_results, 'time': '2026-03-24 10:30:00'}),
                content_type='application/json'
            )

            data = response.get_json()
            assert data['success'] is False
            assert '数据库连接失败' in data['error']

    def test_save_selection_no_body(self, client):
        """测试无请求体"""
        with patch('web_server.selection_record_manager'):
            response = client.post('/api/save_selection',
                data=json.dumps({}),
                content_type='application/json'
            )

            data = response.get_json()
            assert data['success'] is False


# ========== 集成测试：选股执行不再自动保存 ==========

class TestSelectionNoAutoSave:
    """测试选股执行后不再自动保存"""

    def test_run_selection_no_save_result_field(self, client):
        """测试选股结果中不再包含save_result字段"""
        with patch('web_server.registry') as mock_registry, \
             patch('web_server.csv_manager') as mock_csv, \
             patch('web_server.param_lock') as mock_lock, \
             patch('web_server.param_tracker') as mock_tracker, \
             patch('web_server.selection_record_manager') as mock_mgr:

            # mock基础依赖
            mock_lock.check_and_restore.return_value = (False, {})
            mock_tracker.check_changes.return_value = (False, {})
            mock_csv.list_all_stocks.return_value = []
            mock_registry.strategies = {}

            # 执行选股
            response = client.get('/api/select')
            data = response.get_json()

            # 验证返回结果
            assert data['success'] is True
            # 关键断言：不再包含 save_result 字段
            assert 'save_result' not in data
            # 验证 selection_record_manager.save_selection_result 没有被调用
            mock_mgr.save_selection_result.assert_not_called()


if __name__ == '__main__':
    pytest.main(['-v', __file__])
