# 贡献指南

感谢你对 KHunter 项目的关注！我们欢迎各种形式的贡献。

## 📋 贡献方式

### 1. 报告Bug

如果你发现了Bug，请通过以下方式报告：

- **创建Issue**: 在GitHub上创建新Issue，描述：
  - Bug的具体表现
  - 复现步骤
  - 预期行为 vs 实际行为
  - 系统环境（OS、Python版本等）
  - 相关日志或错误信息

### 2. 提出功能建议

- 在GitHub上创建Issue，标题以 `[Feature Request]` 开头
- 详细描述功能的用途和预期效果
- 提供使用场景示例

### 3. 提交代码

#### 准备工作

1. Fork 项目到你的账户
2. Clone 你的Fork：
   ```bash
   git clone https://github.com/YOUR_USERNAME/khunter.git
   cd khunter
   ```
3. 创建特性分支：
   ```bash
   git checkout -b feature/your-feature-name
   ```

#### 开发规范

**代码风格**
- 遵循 PEP 8 规范
- 使用 4 个空格缩进
- 最大行长 100 字符
- 使用有意义的变量名和函数名

**注释规范**
- 函数级注释：每个函数都要有docstring
- 代码注释：每5行代码至少有一条注释
- 中文注释：使用简体中文

**示例**：
```python
def calculate_kdj(df, period=9):
    """
    计算KDJ指标
    
    Args:
        df: 包含OHLC数据的DataFrame
        period: KDJ周期，默认9
    
    Returns:
        DataFrame: 添加了K、D、J列的数据框
    """
    # 计算最高价和最低价
    high = df['high'].rolling(window=period).max()
    low = df['low'].rolling(window=period).min()
    
    # 计算RSV值
    rsv = (df['close'] - low) / (high - low) * 100
    
    # 计算K、D、J值
    # ...
    
    return df
```

**测试规范**
- 为新功能编写单元测试
- 测试覆盖率不低于 80%
- 所有测试必须通过

#### 提交流程

1. 提交代码：
   ```bash
   git add .
   git commit -m "feat: 添加新功能描述"
   ```

2. 推送到你的Fork：
   ```bash
   git push origin feature/your-feature-name
   ```

3. 创建Pull Request：
   - 在GitHub上创建PR
   - 标题清晰简洁
   - 描述包含：
     - 功能说明
     - 相关Issue编号（如 `Fixes #123`）
     - 测试说明
     - 截图或演示（如适用）

#### Commit Message 规范

使用以下格式：
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type 类型**：
- `feat`: 新功能
- `fix`: Bug修复
- `docs`: 文档更新
- `style`: 代码风格调整
- `refactor`: 代码重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建、依赖等

**示例**：
```
feat(strategy): 添加新的选股策略

- 实现了基于MACD的选股逻辑
- 添加了参数配置
- 编写了单元测试

Fixes #123
```

### 4. 改进文档

- 修复文档中的错误或不清楚的地方
- 添加使用示例
- 翻译文档到其他语言
- 改进README或其他文档

## 🔍 代码审查

所有PR都会经过代码审查，审查内容包括：

- ✅ 代码质量和风格
- ✅ 功能完整性和正确性
- ✅ 测试覆盖率
- ✅ 文档完整性
- ✅ 向后兼容性

## 📚 项目结构

```
khunter/
├── strategy/              # 策略模块
│   ├── base_strategy.py   # 策略基类
│   ├── *.py               # 具体策略实现
│   └── strategy_registry.py # 策略注册器
├── utils/                 # 工具模块
│   ├── akshare_fetcher.py # 数据获取
│   ├── technical.py       # 技术指标
│   └── *.py               # 其他工具
├── web/                   # Web前端
│   ├── templates/         # HTML模板
│   └── static/            # 静态资源
├── config/                # 配置文件
├── test/                  # 测试文件
├── doc/                   # 文档
├── main.py                # 主程序
├── web_server.py          # Web服务器
└── requirements.txt       # 依赖列表
```

## 🧪 测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest test/test_strategy.py

# 运行特定测试函数
pytest test/test_strategy.py::test_bowl_rebound

# 显示覆盖率
pytest --cov=strategy --cov=utils
```

### 编写测试

测试文件放在 `test/` 目录，命名规范：`test_*.py`

```python
import pytest
from strategy.bowl_rebound import BowlReboundStrategy

class TestBowlReboundStrategy:
    """碗口反弹策略测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.strategy = BowlReboundStrategy()
    
    def test_calculate_indicators(self):
        """测试指标计算"""
        # 准备测试数据
        df = self.prepare_test_data()
        
        # 执行计算
        result = self.strategy.calculate_indicators(df)
        
        # 验证结果
        assert 'K' in result.columns
        assert 'D' in result.columns
        assert 'J' in result.columns
    
    def prepare_test_data(self):
        """准备测试数据"""
        # ...
        pass
```

## 📝 文档规范

### README

- 清晰的项目描述
- 快速开始指南
- 功能列表
- 技术栈
- 项目结构
- 使用示例

### 代码注释

- 模块级注释：文件顶部说明模块用途
- 类级注释：说明类的用途和主要方法
- 函数级注释：使用docstring说明参数和返回值
- 行级注释：解释复杂逻辑

### 变更日志

在 `CHANGELOG.md` 中记录每个版本的变更：

```markdown
## [1.0.0] - 2026-03-01

### Added
- 新增功能1
- 新增功能2

### Changed
- 修改功能1
- 修改功能2

### Fixed
- 修复Bug1
- 修复Bug2

### Deprecated
- 废弃功能1
```

## 🚀 发布流程

1. 更新版本号（遵循 Semantic Versioning）
2. 更新 CHANGELOG.md
3. 创建Git标签：`git tag v1.0.0`
4. 推送标签：`git push origin v1.0.0`
5. 在GitHub上创建Release

## 💬 讨论和交流

- **GitHub Issues**: 用于Bug报告和功能建议
- **GitHub Discussions**: 用于一般讨论和问题解答
- **Pull Requests**: 用于代码贡献

## 📞 联系方式

- 📧 Email: [项目维护者邮箱]
- 💬 GitHub Issues: [项目地址]/issues
- 🌐 项目主页: [项目地址]

## 🙏 致谢

感谢所有为项目做出贡献的人！

---

**最后更新**: 2026-03-26
