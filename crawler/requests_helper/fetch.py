"""
fetch data utilities
"""
import logging
import re

import requests

from crawler.requests_helper.config import TIMEOUT

logger = logging.getLogger('__name__')


def fetch_wrapper(url, headers, org_params, org_body, process_result_fn):
    """
    return a fn to fetch data for a set of params and body
    """

    def fetch(tasks):
        """
        perform fetching on multiple requests
        replace: org_params, org_body
        :param tasks: list of dict(task_id, task_data{params, body})
        :return:
        """
        tasks_str = ",".join(str(t["task_id"]) for t in tasks)
        logger.info(f'worker start, tasks={tasks_str}')
        with requests.session() as session:
            res = session.post(url, json=org_body.copy(), params={}, headers=headers,timeout=TIMEOUT)
            try:
                cookie = re.search(r'document.cookie="(.*?)"', res.text).group(1)
            except:
                logger.error(f'cannot get cookie from {res.text}')
                return None
            cookies = {cookie.split('=')[0]: cookie.split('=')[1]}

            results = []
            for task in tasks:
                task_id, task_data = task['task_id'], task['task_data']
                params = org_params.copy()
                body = org_body.copy()

                params.update(task_data['params'])
                body.update(task_data['body'])

                res = session.post(url, json=body, params=params,
                                   headers=headers, cookies=cookies, timeout=TIMEOUT)

                if not res.ok:
                    logger.error(
                        f"req fail, args={task_data}, code={res.status_code}, text={res.text[:200]}, headers={headers}, body={body}, params={params}")
                    continue
                try:
                    result = process_result_fn(params, body, res.json(), task_data)
                    results.append(result)
                    logger.info(f"task {task_id} done")
                except requests.exceptions.JSONDecodeError as e:
                    logger.error(
                        f'json decode error, args={task_data}, text={res.text[:200]}, headers={headers}, cookies={cookies}, body={body}, params={params}')
                    raise e
        logger.info(f'worker done, tasks={tasks_str}')
        return results

    return fetch
