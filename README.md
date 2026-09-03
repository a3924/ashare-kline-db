# A股/ETF 前复权日K静态库（ashare-kline-db）

《我的模拟人生·A股版》在线版 L1 数据源，由 jsdelivr 全球 CDN 分发。

- 分片路径：`db/{ver}/{sh|sz}{code}.json`，如 `db/20260901/sh600519.json`
- 分片格式：`{"end":20260901,"k":"20210901,o,c,h,l,v|..."}`（紧凑串，日K，前复权）
- `manifest.json`：ver / end / n；游戏端以 manifest.end 对齐交易日轴并决定启用 L1
- `codes.txt`：全市场 5805 个代码（A股+ETF）
- 更新：`.github/workflows/update-db.yml` 每交易日自动跑 `update_db.py`（东财→腾讯兜底），新建当日目录并更新 manifest
