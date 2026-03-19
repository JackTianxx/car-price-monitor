# 汽车报价监测系统

> **免责声明**：本项目仅供学习和研究使用，严禁用于任何商业目的。本工具采集的数据均来源于公开平台（汽车之家、懂车帝、易车），请使用者自觉遵守相关平台的用户协议及国家法律法规。因使用本工具产生的任何法律责任，由使用者自行承担，开发者不承担任何连带责任。

一个用于抓取和分析汽车经销商报价数据的工具，支持从汽车之家、懂车帝、易车等平台采集数据，帮助快速了解目标车系在全国各地的真实成交价格与折扣行情。

## 功能特性

- **多平台采集**：支持汽车之家、懂车帝、易车同步抓取
- **本品 & 竞品对比**：可同时监测自有品牌与竞争品牌的报价动态
- **任务管理**：异步采集任务，支持单车系、整品牌、全量三种采集范围
- **数据查询**：按省份、城市、平台、日期多维度筛选报价记录
- **统计分析**：省份维度均价、折扣分析，平台数据量对比
- **可视化 UI**：内置 Web 界面，无需额外部署前端

## 界面截图

### 数据概览
![数据概览](overview.png)

### 数据采集
![数据采集](crawl-tab.png)

### 报价明细
![报价明细](prices-tab.png)

## 技术栈

- **后端**：Python 3.11 + FastAPI + SQLAlchemy
- **数据库**：MySQL 8.0
- **部署**：Docker + Docker Compose

## 快速开始

### 环境要求

- Docker & Docker Compose
- 已有 MySQL 实例（或自行添加到 compose 中）

### 部署步骤

1. 克隆仓库

```bash
git clone https://github.com/JackMidn/car-price-monitor.git
cd car-price-monitor
```

2. 配置环境变量（可选，有默认值）

```bash
export DB_HOST=your_mysql_host
export DB_PORT=3306
export DB_USER=root
export DB_PASS=your_password
export DB_NAME=car_price
```

3. 启动服务

```bash
docker-compose up -d
```

4. 访问系统

打开浏览器访问 `http://localhost:8088`

### 本地开发

```bash
pip install -r requirements.txt

DB_HOST=127.0.0.1 DB_PASS=your_password uvicorn app.main:app --reload
```

## API 文档

启动后访问 `http://localhost:8088/docs` 查看完整的 Swagger API 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/series` | 车系列表 |
| POST | `/api/series` | 添加车系 |
| POST | `/api/crawl/start` | 启动采集任务 |
| GET | `/api/crawl/status/{id}` | 查询任务状态 |
| GET | `/api/prices` | 报价数据查询 |
| GET | `/api/stats/overview` | 数据概览统计 |
| GET | `/api/stats/province` | 按省份统计 |

## 项目结构

```
car-price-monitor/
├── app/
│   ├── main.py          # FastAPI 应用入口
│   ├── database.py      # 数据库连接配置
│   ├── models.py        # ORM 数据模型
│   ├── scraper.py       # 多平台爬虫核心
│   ├── routers/
│   │   └── api.py       # API 路由
│   └── static/          # 前端静态文件
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 免责声明

本项目为开源学习项目，使用前请务必阅读以下内容：

1. **仅供学习研究**：本工具仅供个人学习、技术研究使用，严禁用于任何商业目的或大规模数据采集。
2. **遵守平台协议**：使用本工具前，请仔细阅读并遵守汽车之家、懂车帝、易车等目标平台的用户服务协议和爬虫协议（robots.txt）。
3. **合规使用**：使用者须自行确保使用行为符合《网络安全法》《数据安全法》《个人信息保护法》等相关法律法规。
4. **频率控制**：请合理设置采集频率，避免对目标平台服务器造成不必要的负担。
5. **风险自担**：因使用本工具产生的任何法律纠纷、账号封禁、数据损失等风险，由使用者自行承担，开发者不承担任何连带法律责任。
6. **数据准确性**：本工具采集的报价数据仅供参考，不代表实际成交价格，开发者不对数据的准确性、完整性作任何保证。

**如您不同意上述条款，请勿使用本项目。**

## License

MIT
