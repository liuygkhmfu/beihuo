# Webapp 开发说明

`webapp` 是 TK 发货与旺季备货决策台的主应用目录。

- 完整业务规则：[../docs/业务逻辑说明.md](../docs/业务逻辑说明.md)
- 代码架构与模块说明：[../docs/代码架构说明.md](../docs/代码架构说明.md)
- 项目启动与安全说明：[../README.md](../README.md)

核心代码入口：

- `server.py`：本地 HTTP 服务和 API 路由；
- `service.py`：业务流程编排；
- `domain.py`：发货建议与库存预测算法；
- `repository.py`：SQLite 持久化；
- `lingxing_provider.py`：领星数据采集；
- `product_groups.py`：同店铺 `-US` 商品组合并；
- `arrival_tracking.py`：到货表导入及对账；
- `purchase.py`：旺季供应商备货；
- `exporter.py`：Excel 导出。

人工发货节点的主要调用链：

```text
static/app.js
→ POST /api/scenario
→ service.py::recalculate_product_scenario
→ domain.py::recalculate_scenario_plan
→ domain.py::_optimize_inventory_balance
→ 返回重分配节点并刷新库存曲线
```

数量字段分为三层：

- `express_qty` 等：当前参数计算出的系统原始建议；
- `confirmed_*_qty`：已复核或已执行的人工数量；
- `effective_*_qty`：首页、正式列表与 Excel 使用的最终生效口径。

`pending` 决策通过 `draft_scenario_nodes` 恢复草稿，不覆盖正式结果；`reviewed` 和 `executed` 才进入 `effective_*`。

运行全部测试：

```powershell
python -m pytest webapp/tests APIs/tests
```
