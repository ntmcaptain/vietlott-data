import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Dict
import cattrs

import pandas as pd
from bs4 import BeautifulSoup

from vietlott.config.products import ProductConfig, get_config
from vietlott.crawler import collections_helper
from vietlott.crawler.requests_helper import fetch, config as requests_config
from vietlott.crawler.products.base import BaseProduct
from vietlott.crawler.schema.requests import RequestPower655, ORenderInfoCls

logger = logging.getLogger(__name__)


class ProductPower655(BaseProduct):
    name = "power_655"
    url = "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.Game655CompareWebPart,Vietlott.PlugIn.WebParts.ashx"
    page_to_run = 1  # roll every 2 days

    stored_data_dtype = {
        "date": str,
        "id": str,
        "result": "list",
        "page": int,
        "process_time": str,
    }

    orender_info_default = ORenderInfoCls(
        SiteId="main.frontend.vi",
        SiteAlias="main.vi",
        UserSessionId="",
        SiteLang="en",
        IsPageDesign=False,
        ExtraParam1="",
        ExtraParam2="",
        ExtraParam3="",
        SiteURL="",
        WebPage=None,
        SiteName="Vietlott",
        OrgPageAlias=None,
        PageAlias=None,
        RefKey=None,
        FullPageAlias=None,
    )

    org_body = RequestPower655(
        ORenderInfo=orender_info_default,
        Key="23bbd667",
        GameDrawId="",
        ArrayNumbers=[["" for _ in range(18)] for _ in range(5)],
        CheckMulti=False,
        PageIndex=0,
    )
    org_params = {}

    product_config: Optional[ProductConfig] = None

    def __init__(self):
        super(ProductPower655, self).__init__()
        self.product_config = get_config(self.name)
        self.headers = requests_config.headers

    def process_result(self, params, body, res_json, task_data) -> List[Dict]:
        """
        process 645/655 result
        :param params:
        :param body:
        :param res_json:
        :param task_data:
        :return: list of dict data {date, id, result, page, process_time}
        """
        soup = BeautifulSoup(res_json.get("value", {}).get("HtmlContent"), "lxml")
        data = []
        for i, tr in enumerate(soup.select("table tr")):
            if i == 0:
                continue
            tds = tr.find_all("td")
            row = {}

            #
            row["date"] = datetime.strptime(tds[0].text, "%d/%m/%Y").strftime(
                "%Y-%m-%d"
            )
            row["id"] = tds[1].text

            # last number of special
            row["result"] = [
                int(span.text)
                for span in tds[2].find_all("span")
                if span.text.strip() != "|"
            ]
            row["page"] = body.get("PageIndex", -1)
            row["process_time"] = datetime.now().isoformat()

            data.append(row)
        return data

    def crawl(self, run_date_str: str, index_to: int = 1):
        """
        spawn multiple worker to get data from vietlott
        each worker craw a list of dates
        :param product_config:
        :param index_to: earliest page we want to crawl, default = 1 (1 page)
        """

        pool = ThreadPoolExecutor(self.product_config.num_thread)
        page_per_task = math.ceil(index_to / self.product_config.num_thread)
        tasks = collections_helper.chunks_iter(
            [
                {
                    "task_id": i,
                    "task_data": {
                        "params": {},
                        "body": {"PageIndex": i},
                        "run_date_str": run_date_str,
                    },
                }
                for i in range(0, index_to)
            ],
            page_per_task,
        )

        logger.info(f"there are {page_per_task} tasks")
        fetch_fn = fetch.fetch_wrapper(
            self.url,
            requests_config.headers,
            self.org_params,
            cattrs.unstructure(self.org_body),
            self.process_result,
            self.product_config.use_cookies,
        )

        results = pool.map(fetch_fn, tasks)

        # flatten results, as it is 3 level deep
        date_dict = defaultdict(list)
        for l1 in results:
            for l2 in l1:
                for row in l2:
                    date_dict[row["date"]].append(row)

        list_data = []
        for date, date_items in date_dict.items():
            list_data += date_items
        print(list_data)
        df_crawled = pd.DataFrame(list_data)
        logger.info(
            f'crawled data min_date={df_crawled["date"].min()}, max_date={df_crawled["date"].max()}'
            + f", records={len(df_crawled)}"
        )

        # store data
        if self.product_config.raw_path.exists():
            current_data = pd.read_json(
                self.product_config.raw_path, lines=True, dtype=self.stored_data_dtype
            )
            logger.info(
                f'current data min_date={current_data["date"].min()}, max_date={current_data["date"].max()}'
                + f", records={len(current_data)}"
            )
            df_take = df_crawled[~df_crawled["id"].isin(current_data["id"])]
            df_final = pd.concat([current_data, df_take], axis="rows")
        else:
            df_final = df_crawled
        df_final = df_final.sort_values(by="date")

        logger.info(
            f'final data min_date={df_final["date"].min()}, max_date={df_final["date"].max()}'
            + f", records={len(df_final)}"
        )
        df_final.to_json(
            self.product_config.raw_path.absolute(), orient="records", lines=True
        )
        logger.info(f"wrote to file {self.product_config.raw_path.absolute()}")
