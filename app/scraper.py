"""
汽车报价采集核心模块

支持三个平台：
- 汽车之家 (autohome)：通过官方 API 获取经销商报价，分省份/车型两个粒度
- 懂车帝 (dongchedi)：通过开放 API 获取各城市车系和车型报价
- 易车网 (yiche)：解析 HTML 页面获取全国参考价（页面 SPA 化后可能失效）

采集流程：
  run_crawl(task_id) → crawl_autohome / crawl_dongchedi / crawl_yiche → _upsert_prices(db)
"""
import httpx
import json
import asyncio
import re
import urllib.parse
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert as mysql_insert
from app.models import CarPrice, CrawlTask, CarSeries

# ========== 汽车之家 ==========

# 汽车之家请求头，模拟 PC 浏览器访问，Authorization 为接口签名
AUTOHOME_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Authorization": "Basic Y2FyLXBjLW5leHRqc3lJNndab292Om5HM2RsNU5uUHZZRA==",
    "Origin": "https://www.autohome.com.cn",
    "Referer": "https://www.autohome.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}

# 全国省份列表（省级行政区编码），用于汽车之家按省遍历经销商
PROVINCES = [
    (110000, "北京"), (120000, "天津"), (130000, "河北"), (140000, "山西"),
    (150000, "内蒙古"), (210000, "辽宁"), (220000, "吉林"), (230000, "黑龙江"),
    (310000, "上海"), (320000, "江苏"), (330000, "浙江"), (340000, "安徽"),
    (350000, "福建"), (360000, "江西"), (370000, "山东"), (410000, "河南"),
    (420000, "湖北"), (430000, "湖南"), (440000, "广东"), (450000, "广西"),
    (460000, "海南"), (500000, "重庆"), (510000, "四川"), (520000, "贵州"),
    (530000, "云南"), (610000, "陕西"), (620000, "甘肃"), (640000, "宁夏"),
    (650000, "新疆"),
]

# 主要城市 ID 列表（汽车之家城市编码），用于车型级别报价查询
# 覆盖全国 36 个核心城市，兼顾数据量与采集效率
AUTOHOME_CITY_IDS = [
    (110100, "北京"), (120100, "天津"), (310100, "上海"), (500100, "重庆"),
    (440100, "广州"), (440300, "深圳"), (510100, "成都"), (330100, "杭州"),
    (420100, "武汉"), (320100, "南京"), (320500, "苏州"), (610100, "西安"),
    (430100, "长沙"), (210100, "沈阳"), (370200, "青岛"), (410100, "郑州"),
    (350200, "厦门"), (330200, "宁波"), (340100, "合肥"), (530100, "昆明"),
    (230100, "哈尔滨"), (370100, "济南"), (220100, "长春"), (360100, "南昌"),
    (520100, "贵阳"), (140100, "太原"), (460100, "海口"), (650100, "乌鲁木齐"),
    (620100, "兰州"), (640100, "银川"), (130100, "石家庄"), (150100, "呼和浩特"),
    (210200, "大连"), (440600, "佛山"), (330300, "温州"), (320200, "无锡"),
]


async def autohome_fetch_province(
    client: httpx.AsyncClient, series_id: int, series_name: str,
    province_id: int, db_series_id: int
) -> list[dict]:
    """汽车之家: 获取某省份某车系的经销商报价(车系级别)"""
    results = []
    page = 1
    while True:
        url = (
            f"https://autoapi.autohome.com.cn/jxsjs/ics/yhz/dealerlq/v1/dealerlist/list/"
            f"GetDealerListSeriesNew?_appid=pc&sellPhoneType=1&isNeedDealerImg=1"
            f"&seriesId={series_id}&cityId=0&provinceId={province_id}"
            f"&countyId=0&pageIndex={page}&pageSize=20&orderType=0"
        )
        try:
            resp = await client.get(url, headers=AUTOHOME_HEADERS, timeout=15)
            data = resp.json()
        except Exception:
            break

        if data.get("returncode") != 0 or not data.get("result"):
            break

        result = data["result"]
        dealers = result.get("list", [])
        if not dealers:
            break

        for d in dealers:
            info = d.get("dealerInfoBaseOut", {})
            results.append({
                "crawl_date": date.today(),
                "province": info.get("provinceName", ""),
                "city": info.get("cityName", ""),
                "dealer_id": str(d.get("dealerId", "")),
                "dealer_name": info.get("dealerName", ""),
                "dealer_type": d.get("kindStr", ""),
                "series_id": db_series_id,
                "series_name": series_name,
                "spec_name": "",
                "min_price": round(d.get("minNewsPrice", 0) / 10000, 2),
                "max_price": round(d.get("maxNewsPrice", 0) / 10000, 2),
                "guide_price": None,
                "guide_min_price": round(d.get("minOriginalPrice", 0) / 10000, 2),
                "guide_max_price": round(d.get("maxOriginalPrice", 0) / 10000, 2),
                "max_discount": round(d.get("maxPriceOff", 0) / 10000, 2),
                "source": "autohome",
                "price_level": "series",
                "raw_data": json.dumps(d, ensure_ascii=False)[:2000],
            })

        # 判断是否还有下一页
        if page >= result.get("pagecount", 1):
            break
        page += 1
        await asyncio.sleep(0.5)  # 礼貌性延迟，避免请求过于频繁

    return results


async def autohome_fetch_spec_names(
    client: httpx.AsyncClient, series_id: int
) -> dict[int, str]:
    """汽车之家: 通过经销商spec接口获取 specId->specName 映射表"""
    spec_map = {}
    # 第一步：调用城市报价接口拿到一个有效的 dealerId，作为后续查询的入参
    url = (
        f"https://www.autohome.com.cn/ashx/dealer/"
        f"AjaxDealerGetSeriesMinpriceWithSpecs.ashx"
        f"?seriesids={series_id}&cityId=110100"
    )
    try:
        resp = await client.get(url, headers=AUTOHOME_HEADERS, timeout=15)
        data = resp.json()
        dealer_id = None
        if data.get("returncode") == 0 and data.get("result"):
            for si in data["result"]:
                for spec in si.get("specs", []):
                    did = spec.get("dealerId")
                    if did:
                        dealer_id = did
                        break
                if dealer_id:
                    break
        if not dealer_id:
            return spec_map
    except Exception:
        return spec_map

    # 第二步：用经销商 ID 查询该经销商在售的所有车型列表，提取 specId->specName 映射
    url2 = (
        f"https://dealer.autohome.com.cn/api/dealerlq/car/dealercars/getdealerspeclist"
        f"?_appid=dealer&dealerId={dealer_id}&seriesId={series_id}"
    )
    try:
        resp2 = await client.get(url2, headers=AUTOHOME_HEADERS, timeout=15, follow_redirects=True)
        data2 = resp2.json()
        groups = data2.get("result", [])
        if isinstance(groups, list):
            for group in groups:
                for spec in group.get("list", []):
                    sid = spec.get("specId")
                    sname = spec.get("specName")
                    if sid and sname:
                        spec_map[sid] = sname
    except Exception:
        pass

    return spec_map


async def autohome_fetch_spec_prices(
    client: httpx.AsyncClient, series_id: int, series_name: str,
    city_id: int, city_name: str, db_series_id: int,
    spec_name_map: dict[int, str] = None,
) -> list[dict]:
    """汽车之家: 获取某城市某车系的车型级别报价
    使用参考项目验证过的 AjaxDealerGetSeriesMinpriceWithSpecs 接口
    """
    if spec_name_map is None:
        spec_name_map = {}
    results = []
    url = (
        f"https://www.autohome.com.cn/ashx/dealer/"
        f"AjaxDealerGetSeriesMinpriceWithSpecs.ashx"
        f"?seriesids={series_id}&cityId={city_id}"
    )
    try:
        resp = await client.get(url, headers=AUTOHOME_HEADERS, timeout=15)
        data = resp.json()
    except Exception:
        return results

    if data.get("returncode") != 0 or not data.get("result"):
        return results

    # 通过城市->省份映射表推断省份（API 不直接返回省份信息）
    province = CITY_PROVINCE_MAP.get(city_name, "")

    for series_item in data["result"]:
        specs = series_item.get("specs", [])
        for spec in specs:
            news_price = spec.get("newsPrice", 0)
            original_price = spec.get("minOriginalPrice", 0)
            if not news_price:
                continue
            spec_id = spec.get("specId")
            resolved_name = spec_name_map.get(spec_id, spec.get("specName") or f"specId:{spec_id}")
            discount = round((original_price - news_price) / 10000, 2) if original_price > news_price else 0
            results.append({
                "crawl_date": date.today(),
                "province": province,
                "city": city_name,
                "dealer_id": f"ah_spec_{series_id}_{city_id}",
                "dealer_name": f"汽车之家-{city_name}参考价",
                "dealer_type": "平台",
                "series_id": db_series_id,
                "series_name": series_name,
                "spec_name": resolved_name,
                "min_price": round(news_price / 10000, 2),
                "max_price": None,
                "guide_price": round(original_price / 10000, 2) if original_price else None,
                "guide_min_price": None,
                "guide_max_price": None,
                "max_discount": discount if discount > 0 else None,
                "source": "autohome",
                "price_level": "spec",
                "raw_data": json.dumps(spec, ensure_ascii=False)[:2000],
            })

    return results


async def autohome_fetch_dealer_specs(
    client: httpx.AsyncClient, dealer_id: int, series_id: int,
    series_name: str, province: str, city: str, db_series_id: int
) -> list[dict]:
    """汽车之家: 获取经销商下某车系的各车型报价
    使用 dealer.autohome.com.cn 的 getdealerspeclist 接口
    """
    results = []
    url = (
        f"https://dealer.autohome.com.cn/api/dealerlq/car/dealercars/getdealerspeclist"
        f"?_appid=dealer&dealerId={dealer_id}&seriesId={series_id}"
    )
    try:
        resp = await client.get(url, headers=AUTOHOME_HEADERS, timeout=15, follow_redirects=True)
        data = resp.json()
    except Exception:
        return results

    if data.get("returncode") != 0 or not data.get("result"):
        return results

    groups = data["result"]
    if isinstance(groups, dict):
        groups = groups.get("list", []) if "list" in groups else []
    if not isinstance(groups, list):
        return results

    for group in groups:
        spec_list = group.get("list", []) if isinstance(group, dict) else []
        for spec in spec_list:
            news_price = spec.get("newsPrice", 0)
            fct_min = spec.get("fctMinPrice", 0)
            if not news_price and not fct_min:
                continue
            results.append({
                "crawl_date": date.today(),
                "province": province,
                "city": city,
                "dealer_id": str(dealer_id),
                "dealer_name": f"经销商{dealer_id}",
                "dealer_type": "4S店",
                "series_id": db_series_id,
                "series_name": series_name,
                "spec_name": spec.get("specName", ""),
                "min_price": round(news_price / 10000, 2) if news_price else None,
                "max_price": None,
                "guide_price": round(fct_min / 10000, 2) if fct_min else None,
                "guide_min_price": None,
                "guide_max_price": None,
                "max_discount": round((fct_min - news_price) / 10000, 2) if fct_min > news_price else None,
                "source": "autohome",
                "price_level": "spec",
                "raw_data": json.dumps(spec, ensure_ascii=False)[:2000],
            })

    return results


async def crawl_autohome(series: CarSeries, task: CrawlTask, db: Session):
    """汽车之家: 完整采集一个车系"""
    if not series.autohome_id:
        return 0

    total = 0
    async with httpx.AsyncClient() as client:
        # 第1步：车系级别 - 遍历全国省份，获取各省经销商报价列表
        for i, (prov_id, prov_name) in enumerate(PROVINCES):
            task.message = f"[汽车之家] 车系报价: {prov_name} ({i+1}/{len(PROVINCES)})"
            db.commit()

            dealers = await autohome_fetch_province(
                client, series.autohome_id, series.name, prov_id, series.id
            )
            if dealers:
                _upsert_prices(db, dealers)
                total += len(dealers)

            await asyncio.sleep(0.3)

        # 第2步：获取车型名称映射表（specId -> 车型名称），避免返回结果只有 ID
        task.message = f"[汽车之家] 获取车型名称映射..."
        db.commit()
        spec_name_map = await autohome_fetch_spec_names(client, series.autohome_id)

        # 第3步：车型级别 - 遍历主要城市，获取各车型具体报价（精度更高）
        task.message = f"[汽车之家] 采集车型级别报价..."
        db.commit()
        for i, (city_id, city_name) in enumerate(AUTOHOME_CITY_IDS):
            specs = await autohome_fetch_spec_prices(
                client, series.autohome_id, series.name,
                city_id, city_name, series.id, spec_name_map
            )
            if specs:
                _upsert_prices(db, specs)
                total += len(specs)
            await asyncio.sleep(0.3)

    return total


# ========== 懂车帝 ==========

# 懂车帝请求头，模拟 PC 端浏览器
DONGCHEDI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Referer": "https://www.dongchedi.com/",
}

# 懂车帝采集城市列表（50个主要城市），按城市名直接查询，无需编码
DONGCHEDI_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "南京",
    "重庆", "天津", "苏州", "西安", "长沙", "沈阳", "青岛", "郑州",
    "大连", "东莞", "宁波", "厦门", "福州", "无锡", "合肥", "昆明",
    "哈尔滨", "济南", "佛山", "长春", "温州", "石家庄", "南宁", "常州",
    "泉州", "南昌", "贵阳", "太原", "烟台", "嘉兴", "南通", "金华",
    "珠海", "惠州", "徐州", "海口", "乌鲁木齐", "绍兴", "中山", "台州",
    "兰州", "银川",
]

# 城市->省份映射表，用于在 API 不返回省份时补全省份字段
CITY_PROVINCE_MAP = {
    "北京": "北京", "上海": "上海", "天津": "天津", "重庆": "重庆",
    "广州": "广东", "深圳": "广东", "东莞": "广东", "佛山": "广东",
    "珠海": "广东", "惠州": "广东", "中山": "广东",
    "成都": "四川", "杭州": "浙江", "武汉": "湖北", "南京": "江苏",
    "苏州": "江苏", "无锡": "江苏", "南通": "江苏", "常州": "江苏", "徐州": "江苏",
    "西安": "陕西", "长沙": "湖南", "沈阳": "辽宁", "大连": "辽宁",
    "青岛": "山东", "济南": "山东", "烟台": "山东",
    "郑州": "河南", "宁波": "浙江", "温州": "浙江", "嘉兴": "浙江",
    "绍兴": "浙江", "金华": "浙江", "台州": "浙江",
    "厦门": "福建", "福州": "福建", "泉州": "福建",
    "合肥": "安徽", "昆明": "云南", "哈尔滨": "黑龙江", "长春": "吉林",
    "南宁": "广西", "南昌": "江西", "贵阳": "贵州", "太原": "山西",
    "海口": "海南", "乌鲁木齐": "新疆", "兰州": "甘肃", "银川": "宁夏",
    "石家庄": "河北",
}


async def dongchedi_search_series(client: httpx.AsyncClient, name: str) -> int | None:
    """懂车帝: 搜索车系ID"""
    encoded = urllib.parse.quote(name)
    url = (
        f"https://www.dongchedi.com/motor/searchapi/search_content/"
        f"?keyword={encoded}&offset=0&count=5&cur_tab=1"
        f"&city_name=%E5%8C%97%E4%BA%AC&motor_source=pc&format=json"
    )
    try:
        resp = await client.get(url, headers=DONGCHEDI_HEADERS, timeout=10)
        data = resp.json()
        items = data.get("data", [])
        if isinstance(items, list):
            for item in items:
                sid = item.get("series_id")
                if sid:
                    return sid
    except Exception:
        pass
    return None


async def dongchedi_get_car_ids(client: httpx.AsyncClient, series_id: int, city_name: str = "北京") -> list[int]:
    """懂车帝: 获取车系下的车款ID列表"""
    encoded_city = urllib.parse.quote(city_name)
    url = (
        f"https://www.dongchedi.com/motor/car_page/m/v1/get_head/"
        f"?series_id={series_id}&city_name={encoded_city}&data_from=pc_station"
    )
    try:
        resp = await client.get(url, headers=DONGCHEDI_HEADERS, timeout=10)
        data = resp.json()
        # car_id_list 存储在 concern_obj 下，值为逗号分隔的字符串，如 "12345,67890"
        concern = data.get("concern_obj", {})
        car_id_str = concern.get("car_id_list", "")
        if car_id_str:
            return [int(x) for x in car_id_str.split(",") if x.strip()]
    except Exception:
        pass
    return []


async def dongchedi_fetch_car_prices(
    client: httpx.AsyncClient, car_ids: list[int], series_name: str,
    city_name: str, db_series_id: int
) -> list[dict]:
    """懂车帝: 获取各车型在某城市的报价"""
    results = []
    encoded_city = urllib.parse.quote(city_name)
    province = CITY_PROVINCE_MAP.get(city_name, "")

    for car_id in car_ids:
        url = (
            f"https://www.dongchedi.com/motor/car_page/v4/get_entity_json/"
            f"?car_id_list={car_id}&city_name={encoded_city}"
        )
        try:
            resp = await client.get(url, headers=DONGCHEDI_HEADERS, timeout=10)
            data = resp.json()
            car_info_list = data.get("data", {}).get("car_info", [])
            for ci in car_info_list:
                dealer_price = ci.get("dealer_price_value", 0)
                official_price = ci.get("info", {}).get("official_price", {}).get("compare_value", 0)
                car_name = ci.get("car_name", "")
                year = ci.get("car_year", "")
                spec_name = f"{year}款 {series_name} {car_name}" if year else car_name
                discount = round(official_price - dealer_price, 2) if official_price and dealer_price and official_price > dealer_price else 0

                results.append({
                    "crawl_date": date.today(),
                    "province": province,
                    "city": city_name,
                    "dealer_id": f"dcd_{car_id}_{city_name}",
                    "dealer_name": f"懂车帝-{city_name}参考价",
                    "dealer_type": "平台",
                    "series_id": db_series_id,
                    "series_name": series_name,
                    "spec_name": spec_name,
                    "min_price": dealer_price if dealer_price else None,
                    "max_price": None,
                    "guide_price": official_price if official_price else None,
                    "guide_min_price": None,
                    "guide_max_price": None,
                    "max_discount": discount if discount > 0 else None,
                    "source": "dongchedi",
                    "price_level": "spec",
                    "raw_data": json.dumps(ci, ensure_ascii=False)[:2000],
                })
        except Exception:
            continue
        await asyncio.sleep(0.2)

    return results


async def dongchedi_fetch_refer_price(
    client: httpx.AsyncClient, series_id: int, series_name: str,
    city_name: str, db_series_id: int
) -> dict | None:
    """懂车帝: 获取车系在某城市的经销商报价概况"""
    encoded_city = urllib.parse.quote(city_name)
    url = (
        f"https://www.dongchedi.com/cloud/api/invoke/get_price_by_series_id"
        f"?series_id={series_id}&city_name={encoded_city}"
    )
    try:
        resp = await client.get(url, headers=DONGCHEDI_HEADERS, timeout=10)
        data = resp.json()
        dd = data.get("data", {})
        dealer_low = dd.get("DealerLowPrice", 0)
        dealer_high = dd.get("DealerHighPrice", 0)
        official_low = dd.get("OfficialLowPrice", 0)
        official_high = dd.get("OfficialHighPrice", 0)
        if not dealer_low and not official_low:
            return None
        province = CITY_PROVINCE_MAP.get(city_name, "")
        return {
            "crawl_date": date.today(),
            "province": province,
            "city": city_name,
            "dealer_id": f"dcd_series_{series_id}_{city_name}",
            "dealer_name": f"懂车帝-{city_name}参考价",
            "dealer_type": "平台",
            "series_id": db_series_id,
            "series_name": series_name,
            "spec_name": "",
            "min_price": dealer_low if dealer_low else None,
            "max_price": dealer_high if dealer_high else None,
            "guide_price": None,
            "guide_min_price": official_low if official_low else None,
            "guide_max_price": official_high if official_high else None,
            "max_discount": round(official_high - dealer_low, 2) if official_high and dealer_low else None,
            "source": "dongchedi",
            "price_level": "series",
            "raw_data": json.dumps(dd, ensure_ascii=False)[:2000],
        }
    except Exception:
        return None


async def crawl_dongchedi(series: CarSeries, task: CrawlTask, db: Session):
    """懂车帝: 完整采集一个车系"""
    total = 0
    async with httpx.AsyncClient() as client:
        dcd_id = series.dongchedi_id
        if not dcd_id:
            dcd_id = await dongchedi_search_series(client, series.name)
            if dcd_id:
                series.dongchedi_id = dcd_id
                db.commit()

        if not dcd_id:
            return 0

        # 先获取该车系下的所有车款 ID（每款车型对应一个 car_id）
        task.message = f"[懂车帝] 获取{series.name}车款列表..."
        db.commit()
        car_ids = await dongchedi_get_car_ids(client, dcd_id)

        for i, city in enumerate(DONGCHEDI_CITIES):
            task.message = f"[懂车帝] 采集: {city} ({i+1}/{len(DONGCHEDI_CITIES)})"
            db.commit()

            # 车系级别报价（价格区间，快速了解该城市大盘行情）
            refer = await dongchedi_fetch_refer_price(client, dcd_id, series.name, city, series.id)
            if refer:
                _upsert_prices(db, [refer])
                total += 1

            # 车型级别报价（精确到具体款型，最多取前10款避免请求过多）
            if car_ids:
                specs = await dongchedi_fetch_car_prices(client, car_ids[:10], series.name, city, series.id)
                if specs:
                    _upsert_prices(db, specs)
                    total += len(specs)

            await asyncio.sleep(0.5)

    return total


# ========== 易车网 ==========

# 易车网请求头，注意：易车网主要页面已 SPA 化，HTML 爬取可能无法获取动态渲染内容
YICHE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


async def yiche_fetch_series(
    client: httpx.AsyncClient, slug: str, series_name: str, db_series_id: int
) -> list[dict]:
    """易车网: 爬取车系报价页面"""
    results = []
    url = f"https://car.yiche.com/{slug}/"
    try:
        resp = await client.get(url, headers=YICHE_HEADERS, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return results
        html = resp.text

        # 用正则从 HTML 中提取车系最高降价幅度
        discount_match = re.search(r'最高降\s*([\d.]+)\s*万', html)

        # 提取车型列表：车名、指导价、经销商报价
        # 易车页面结构：<a class="car-item-jump">车名</a> ... <span class="fouth">指导价</span> <span class="five">报价</span>
        car_names = re.findall(r'class="car-item-jump"[^>]*>([^<]+)', html)
        guide_prices = re.findall(r'class="fouth"[^>]*>\s*([\d.]+)', html)
        dealer_prices = re.findall(r'class="five"[^>]*>\s*([\d.]+)', html)

        count = min(len(car_names), len(guide_prices), len(dealer_prices))
        for i in range(count):
            name = car_names[i].strip()
            try:
                gp = float(guide_prices[i])
                dp = float(dealer_prices[i])
            except (ValueError, IndexError):
                continue
            results.append({
                "crawl_date": date.today(),
                "province": "",
                "city": "",
                "dealer_id": f"yiche_{slug}_{i}",
                "dealer_name": "易车网全国参考价",
                "dealer_type": "平台",
                "series_id": db_series_id,
                "series_name": series_name,
                "spec_name": name,
                "min_price": dp,
                "max_price": None,
                "guide_price": gp,
                "guide_min_price": None,
                "guide_max_price": None,
                "max_discount": round(gp - dp, 2) if gp > dp else None,
                "source": "yiche",
                "price_level": "spec",
                "raw_data": None,
            })

        # 车型级别未提取到数据时，降级尝试提取车系级别的价格区间
        if not results:
            guide_match = re.search(r'指导价[：:]\s*([\d.]+)\s*[-~]\s*([\d.]+)\s*万', html)
            dealer_match = re.search(r'(?:经销商报价|本地报价)[：:]\s*([\d.]+)\s*[-~]\s*([\d.]+)\s*万', html)
            if guide_match or dealer_match:
                results.append({
                    "crawl_date": date.today(),
                    "province": "",
                    "city": "",
                    "dealer_id": f"yiche_{slug}",
                    "dealer_name": "易车网全国参考价",
                    "dealer_type": "平台",
                    "series_id": db_series_id,
                    "series_name": series_name,
                    "spec_name": "",
                    "min_price": float(dealer_match.group(1)) if dealer_match else None,
                    "max_price": float(dealer_match.group(2)) if dealer_match else None,
                    "guide_price": None,
                    "guide_min_price": float(guide_match.group(1)) if guide_match else None,
                    "guide_max_price": float(guide_match.group(2)) if guide_match else None,
                    "max_discount": float(discount_match.group(1)) if discount_match else None,
                    "source": "yiche",
                    "price_level": "series",
                    "raw_data": None,
                })

    except Exception:
        pass

    return results


async def crawl_yiche(series: CarSeries, task: CrawlTask, db: Session):
    """易车网: 采集一个车系（易车网已SPA化，HTML解析可能无法获取数据）"""
    if not series.yiche_slug:
        return 0

    total = 0
    async with httpx.AsyncClient() as client:
        task.message = f"[易车网] 采集: {series.name}"
        db.commit()

        rows = await yiche_fetch_series(client, series.yiche_slug, series.name, series.id)
        if rows:
            _upsert_prices(db, rows)
            total += len(rows)
        else:
            task.message = f"[易车网] {series.name}: 未获取到数据（易车网页面需JS渲染）"
            db.commit()

    return total


# ========== 公共方法 ==========

def _upsert_prices(db: Session, rows: list[dict]):
    """
    批量写入报价数据（INSERT ... ON DUPLICATE KEY UPDATE）

    利用 MySQL 的 upsert 语义：数据已存在则更新价格字段，不存在则插入新记录。
    唯一键由 crawl_date + dealer_id + series_name + spec_name + source 组成。
    """
    for row in rows:
        if row.get("spec_name") is None:
            row["spec_name"] = ""
        stmt = mysql_insert(CarPrice).values(**row)
        stmt = stmt.on_duplicate_key_update(
            min_price=stmt.inserted.min_price,
            max_price=stmt.inserted.max_price,
            guide_price=stmt.inserted.guide_price,
            guide_min_price=stmt.inserted.guide_min_price,
            guide_max_price=stmt.inserted.guide_max_price,
            max_discount=stmt.inserted.max_discount,
            dealer_name=stmt.inserted.dealer_name,
            raw_data=stmt.inserted.raw_data,
            created_at=datetime.now(),
        )
        db.execute(stmt)
    db.commit()


async def run_crawl(task_id: int, db_factory, sources: list[str] = None):
    """
    采集任务主入口（异步执行，由 FastAPI 后台任务调用）

    根据 task.scope 决定采集范围：
    - single：仅采集指定车系
    - brand：采集同品牌下所有激活的车系
    - all：采集数据库中全部激活车系

    sources 控制采集哪些平台，默认三个平台全采。
    任务状态实时写回数据库，前端轮询 /api/crawl/status/{id} 查看进度。
    """
    if sources is None:
        sources = ["autohome", "dongchedi", "yiche"]

    db: Session = db_factory()
    try:
        task = db.query(CrawlTask).get(task_id)
        task.status = "running"
        task.message = "正在准备采集..."
        db.commit()

        if task.scope == "all":
            series_list = db.query(CarSeries).filter(CarSeries.is_active == True).all()
        elif task.scope == "brand":
            ref = db.query(CarSeries).filter(CarSeries.name == task.series_name).first()
            if ref:
                series_list = db.query(CarSeries).filter(
                    CarSeries.brand == ref.brand, CarSeries.is_active == True
                ).all()
            else:
                series_list = []
        else:
            s = db.query(CarSeries).filter(CarSeries.name == task.series_name).first()
            series_list = [s] if s else []

        if not series_list:
            task.status = "error"
            task.message = f"未找到车系「{task.series_name}」"
            task.finished_at = datetime.now()
            db.commit()
            return

        grand_total = 0
        for idx, series in enumerate(series_list):
            task.message = f"采集 {series.name} ({idx+1}/{len(series_list)})..."
            db.commit()

            for src in sources:
                try:
                    if src == "autohome" and series.autohome_id:
                        count = await crawl_autohome(series, task, db)
                        grand_total += count
                    elif src == "dongchedi":
                        count = await crawl_dongchedi(series, task, db)
                        grand_total += count
                    elif src == "yiche" and series.yiche_slug:
                        count = await crawl_yiche(series, task, db)
                        grand_total += count
                except Exception as e:
                    task.message = f"[{src}] {series.name} 出错: {str(e)[:100]}"
                    db.commit()

                task.total = grand_total
                db.commit()

        task.status = "done"
        task.total = grand_total
        task.message = f"采集完成，共 {grand_total} 条报价数据"
        task.finished_at = datetime.now()
        db.commit()

    except Exception as e:
        task = db.query(CrawlTask).get(task_id)
        task.status = "error"
        task.message = f"采集出错: {str(e)[:200]}"
        task.finished_at = datetime.now()
        db.commit()
    finally:
        db.close()
