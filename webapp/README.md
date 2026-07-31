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

运行全部测试：

```powershell
python -m pytest webapp/tests APIs/tests
```
