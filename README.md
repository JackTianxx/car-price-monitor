# 汽车报价监测系统

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

> **免责声明**：本项目仅供个人学习与技术研究使用，严禁商业用途。详见文末[免责声明](#免责声明)。

多平台汽车经销商报价数据采集与分析工具。支持**汽车之家、懂车帝、易车**三平台同步抓取，帮助你快速了解目标车系在全国各地的真实成交价格与优惠行情。

## 能解决什么问题

- 想知道某款车**全国各城市真实成交价**，不想一个个城市手动查
- 需要同时监测**本品牌 + 竞品**的价格动态，对比优惠力度
- 希望有一份**历史价格数据**，分析折扣趋势

## 界面截图

### 数据概览 — 省份分布与采集历史
![数据概览](overview.png)

### 数据采集 — 一键触发多平台采集
![数据采集](crawl-tab.png)

### 报价明细 — 多维度筛选查询
![报价明细](prices-tab.png)

## 功能特性

- **多平台采集**：汽车之家（经销商+车型两粒度）、懂车帝（50城市）、易车网
- **本品 & 竞品**：同时监测自有品牌与竞争品牌，支持自定义车系配置
- **异步任务**：后台异步采集，实时进度推送，支持单车系 / 整品牌 / 全量三种范围
- **多维查询**：按省份、城市、来源、日期、本品/竞品筛选报价记录
- **统计分析**：省份均价与折扣分布、各平台数据量对比
- **开箱即用**：内置 Web 界面 + Docker 一键部署，无需额外配置前端

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Python 3.11 + FastAPI |
| 数据库 ORM | SQLAlchemy 2.0 |
| 数据库 | MySQL 8.0 |
| HTTP 客户端 | httpx（异步） |
| 部署 | Docker + Docker Compose |

## 快速开始

### 环境要求

- Docker & Docker Compose
- 已有 MySQL 实例（或修改 compose 文件自行添加）

### 一键部署

```bash
# 1. 克隆仓库
git clone https://github.com/JackTianxx/car-price-monitor.git
cd car-price-monitor

# 2. 配置数据库连接（也可直接用环境变量）
export DB_HOST=your_mysql_host
export DB_PASS=your_password

# 3. 启动
docker-compose up -d

# 4. 打开浏览器
open http://localhost:8088
```

### 本地开发

```bash
pip install -r requirements.txt

DB_HOST=127.0.0.1 DB_PASS=your_password uvicorn app.main:app --reload --port 8088
```

首次启动会自动建库建表，并写入预置的东风日产本品及竞品车系种子数据。

## API 文档

启动后访问 `http://localhost:8088/docs` 查看完整 Swagger 文档。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/series` | 车系列表（支持按 brand_type 筛选） |
| POST | `/api/series` | 添加自定义车系 |
| PUT | `/api/series/{id}` | 更新车系配置 |
| DELETE | `/api/series/{id}` | 删除车系 |
| POST | `/api/crawl/start` | 启动采集任务 |
| GET | `/api/crawl/status/{id}` | 查询任务实时进度 |
| GET | `/api/crawl/history` | 历史任务列表 |
| GET | `/api/prices` | 报价数据分页查询 |
| GET | `/api/stats/overview` | 数据总览统计 |
| GET | `/api/stats/province` | 按省份统计均价与折扣 |

## 项目结构

```
car-price-monitor/
├── app/
│   ├── main.py          # FastAPI 应用入口，数据库初始化 & 路由注册
│   ├── database.py      # 数据库连接配置，Session 工厂
│   ├── models.py        # ORM 模型：CarSeries / CarPrice / CrawlTask
│   ├── scraper.py       # 多平台爬虫核心（汽车之家 / 懂车帝 / 易车）
│   ├── routers/
│   │   └── api.py       # REST API 路由实现
│   └── static/
│       └── index.html   # 内置前端页面
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 如何添加自定义车系

通过接口或前端「车系管理」页签添加，需要提供各平台的 ID：

- **汽车之家 ID**：打开车系页面，URL 中的数字即为 `autohome_id`，如 `autohome.com.cn/425/` → ID 为 `425`
- **懂车帝 ID**：可留空，系统首次采集时会自动通过搜索接口补全
- **易车 slug**：易车车系页面 URL 中的拼音部分，如 `car.yiche.com/xuanyi/` → slug 为 `xuanyi`

## 免责声明

本项目为开源学习项目，使用前请务必阅读以下内容：

1. **仅供学习研究**：本工具仅供个人学习、技术研究使用，严禁用于任何商业目的或大规模数据采集。
2. **遵守平台协议**：使用前请阅读并遵守汽车之家、懂车帝、易车等目标平台的用户服务协议和爬虫协议（robots.txt）。
3. **合规使用**：使用者须自行确保行为符合《网络安全法》《数据安全法》《个人信息保护法》等相关法律法规。
4. **频率控制**：请合理设置采集频率，代码中已内置延迟，请勿人为去除，避免对目标平台造成不必要的负担。
5. **风险自担**：因使用本工具产生的任何法律纠纷、账号封禁、数据损失等风险，由使用者自行承担，开发者不承担任何连带法律责任。
6. **数据准确性**：采集数据仅供参考，不代表实际成交价格，开发者不对数据的准确性、完整性作任何保证。

**如您不同意上述条款，请勿使用本项目。**

## 联系方式

如有问题、建议或合作意向，欢迎通过以下方式联系：

- **Email**：pe_tianjunjie@126.com
- **GitHub Issues**：[提交 Issue](https://github.com/JackTianxx/car-price-monitor/issues)

## License

[MIT](LICENSE)
