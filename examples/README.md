# 示例数据说明（T6.1）

## renewable_energy_gdp.csv

从完整 OWID 数据集中提取的演示子集，用于快速联调与小规模演示。

| 属性 | 值 |
|------|-----|
| 行数 × 列数 | 48 行 × 4 列 |
| 国家 | China（24 行）、United States（24 行） |
| 年份范围 | 2000–2023 |
| 列 | `country`（类别）、`year`（数值）、`gdp`（数值，国际元，缺失 2 个观测）、`renewables_share_energy`（数值，%） |
| 已知数据特征 | 两国各有 1 年 GDP 缺失；占比列无缺失——可用于演示缺失值报告 |

### 来源与许可

- **来源**：[Our World in Data – Energy Data](https://github.com/owid/energy-data)（OWID 能源数据集，基于 Energy Institute Statistical Review of World Energy 等公开数据汇编）
- **许可**：Creative Commons BY 4.0（署名即可自由使用与再分发）
- **完整数据集**：项目根目录 `owid-energy-data.csv`（23,377 行 × 130 列，1900–2025，314 个国家/地区，约 16 MB，未纳入 Git 提交时请从上述官方渠道下载）

### 提取命令（可复现）

```powershell
python -c "import pandas as pd; df = pd.read_csv('owid-energy-data.csv', usecols=['country','year','gdp','renewables_share_energy']); sub = df[df['country'].isin(['China','United States']) & df['year'].between(2000,2023)]; sub.to_csv('examples/renewable_energy_gdp.csv', index=False)"
```

### 配合本子集的快速演示

```powershell
.venv\Scripts\python.exe app.py --data examples\renewable_energy_gdp.csv --max-turns 6 --hypothesis "对比中美两国 2000-2023 年可再生能源占比与 GDP 的描述统计"
```
