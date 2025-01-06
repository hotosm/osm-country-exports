import argparse
import copy
import json
import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CountryProcessor:
    def __init__(self, config_json=None, language_json="language.json"):
        if config_json is None:
            raise ValueError("Config JSON couldn't be found")

        if isinstance(config_json, dict):
            self.config = config_json
        elif os.path.exists(config_json):
            with open(config_json) as f:
                self.config = json.load(f)
        else:
            raise ValueError("Invalid value for config_json")
        self.languages = None
        if isinstance(language_json, dict):
            self.languages = language_json
        elif os.path.exists(language_json):
            with open(language_json) as f:
                self.languages = json.load(f)

        self.RAW_DATA_API_BASE_URL = os.environ.get("RAW_DATA_API_BASE_URL")
        self.RAWDATA_API_AUTH_TOKEN = os.environ.get("RAWDATA_API_AUTH_TOKEN")

    def generate_filtered_config(self, export):
        config_temp = copy.deepcopy(self.config)
        for key in export["properties"].keys():
            # overwrite config.json keys if it is already in predefined export keys
            config_temp[key] = export["properties"].get(key)
        print(config_temp.get("iso3"))
        if config_temp.get("iso3"):
            if self.languages:
                language_select = self.languages.get(config_temp.get("iso3"))
                if language_select:
                    for category_group in config_temp.get("categories"):
                        for category in category_group:
                            category_group[category]["select"] = (
                                category_group[category].get("select") + language_select
                            )
        return json.dumps(config_temp)

    def process_export(self, export):
        request_config = self.generate_filtered_config(export)
        response = self.retry_post_request(request_config)
        return response

    def retry_post_request(self, request_config):
        retry_strategy = Retry(
            total=2,  # Number of retries
            status_forcelist=[429, 502],
            allowed_methods=["POST"],
            backoff_factor=1,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        with requests.Session() as req_session:
            req_session.mount("https://", adapter)
            req_session.mount("http://", adapter)

        try:
            HEADERS = {
                "Content-Type": "application/json",
                "Access-Token": self.RAWDATA_API_AUTH_TOKEN,
            }
            RAW_DATA_SNAPSHOT_URL = f"{self.RAW_DATA_API_BASE_URL}/custom/snapshot/"
            response = req_session.post(
                RAW_DATA_SNAPSHOT_URL,
                headers=HEADERS,
                data=request_config,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["task_id"]
        except requests.exceptions.RetryError as e:
            self.handle_rate_limit()
            return self.retry_post_request(request_config)

    def handle_rate_limit(self):
        logging.warning("Rate limit reached. Waiting for 1 minute before retrying.")
        time.sleep(61)

    def retry_get_request(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error("Error in GET request: %s", str(e))
            return {"status": "ERROR"}

    def track_tasks_status(self, task_ids):
        results = {}

        for task_id in task_ids:
            status_url = f"{self.RAW_DATA_API_BASE_URL}/tasks/status/{task_id}/"
            response = self.retry_get_request(status_url)

            if response["status"] == "SUCCESS":
                results[task_id] = response["result"]
            elif response["status"] in ["PENDING", "STARTED"]:
                while True:
                    response = self.retry_get_request(status_url)
                    if response["status"] in ["SUCCESS", "ERROR", "FAILURE"]:
                        results[task_id] = response["result"]
                        logging.info(
                            "Task %s is %s , Moving to fetch next one",
                            task_id,
                            response["status"],
                        )
                        break
                    logging.warning(
                        "Task %s is %s. Retrying in 30 seconds...",
                        task_id,
                        response["status"],
                    )
                    time.sleep(30)
            else:
                results[task_id] = "FAILURE"
        logging.info("%s tasks stats is fetched, Dumping result", len(results))
        with open("result.json", "w") as f:
            json.dump(results, f, indent=2)
        logging.info("Done ! Find result at result.json")

    def clean_hdx_export_response(self, feature):
        feature["properties"].pop("id")
        feature["properties"]["dataset"]["dataset_locations"] = list(
            feature["properties"]["dataset"]["dataset_locations"]
        )
        feature["properties"].pop("cid")
        if feature["properties"].get("categories") is None:
            feature["properties"].pop("categories")
        if feature["geometry"].get("type") is None:
            feature.pop("geometry")
        else:
            feature.pop("iso3")
        return feature

    def get_scheduled_exports(self, frequency):
        combined_results = []
        max_retries = 3
        limit = 100
        skip = 0

        while True:
            for retry in range(max_retries):
                try:
                    active_projects_api_url = f"{self.RAW_DATA_API_BASE_URL}/cron/?update_frequency={frequency}&skip={skip}&limit={limit}"
                    response = requests.get(active_projects_api_url, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    if not data:
                        return combined_results
                    combined_results.extend(data)
                    break
                except Exception as e:
                    logging.warning(
                        f"Request failed (attempt {retry + 1}/{max_retries}): {e}"
                    )
            else:
                raise Exception(
                    f"Failed to fetch scheduled projects after {max_retries} attempts"
                )

            skip += limit

    def get_hdx_project_details(self, key, value):
        project_api_url = f"{self.RAW_DATA_API_BASE_URL}/cron/?{key}={value}"
        max_retries = 3
        for retry in range(max_retries):
            try:
                logging.info("Fetching Hdx export details %s:%s", key, value)
                response = requests.get(project_api_url, timeout=20)
                response.raise_for_status()
                response = response.json()
                if not response[0]:
                    logging.error("Feature not found")
                    return None
                feature = self.clean_hdx_export_response(response[0])
                return feature
            except Exception as ex:
                logging.warning(
                    "Request failed (attempt %s/%s): %s", retry + 1, max_retries, ex
                )
        logging.error(
            "Failed to fetch hdx export details %s:%s after 3 retries", key, value
        )
        return None

    def init_call(self, iso3=None, ids=None, fetch_scheduled_exports=None):
        all_export_details = []
        if iso3:
            for country in iso3:
                all_export_details.append(
                    self.get_hdx_project_details(key="iso3", value=country.upper())
                )
        if ids:
            for hdx_id in ids:
                all_export_details.append(
                    self.get_hdx_project_details(key="id", value=hdx_id)
                )

        if fetch_scheduled_exports:
            frequency = fetch_scheduled_exports
            logger.info(
                "Retrieving scheduled projects with frequency of  %s",
                frequency,
            )
            scheduled_exports = self.get_scheduled_exports(frequency)
            for export in scheduled_exports:
                if export:
                    all_export_details.append(self.clean_hdx_export_response(export))

        task_ids = []

        logger.info("Supplied %s exports", len(all_export_details))
        for export in all_export_details:
            if export:
                task_id = self.process_export(export)
                if task_id is not None:
                    task_ids.append(task_id)
        logging.info(
            "Request : All request to %s has been sent, Logging %s task_ids",
            self.RAW_DATA_API_BASE_URL,
            len(task_ids),
        )
        logging.info(task_ids)
        return task_ids


def lambda_handler(event, context):
    config_json = os.environ.get("CONFIG_JSON", None)
    if config_json is None:
        raise ValueError("Config JSON couldn't be found in env")
    if os.environ.get("RAWDATA_API_AUTH_TOKEN", None) is None:
        raise ValueError("RAWDATA_API_AUTH_TOKEN environment variable not found.")
    iso3 = event.get("iso3", None)
    ids = event.get("ids", None)
    fetch_scheduled_exports = event.get("fetch_scheduled_exports", "daily")

    hdx_processor = CountryProcessor(config_json)
    hdx_processor.init_call(
        iso3=iso3, ids=ids, fetch_scheduled_exports=fetch_scheduled_exports
    )


def main():
    parser = argparse.ArgumentParser(
        description="Triggers extraction request for Hdx extractions projects"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--iso3",
        nargs="+",
        type=str,
        help="List of country ISO3 codes, add multiples by space",
    )
    group.add_argument(
        "--ids",
        nargs="+",
        type=int,
        help="List of hdx exports id, add multiples by space",
    )
    group.add_argument(
        "--fetch-scheduled-exports",
        nargs="?",
        const="daily",
        type=str,
        metavar="frequency",
        help="Fetch schedule exports with an optional frequency (default is daily)",
    )
    parser.add_argument(
        "--track",
        action="store_true",
        default=False,
        help="Track the status of tasks and dumps result, Use it carefully as it waits for all tasks to complete",
    )
    args = parser.parse_args()

    config_json = os.environ.get("CONFIG_JSON", "config.json")
    language_json = os.environ.get("LANGUAGE_JSON", "language.json")
    if os.environ.get("RAWDATA_API_AUTH_TOKEN", None) is None:
        raise ValueError("RAWDATA_API_AUTH_TOKEN environment variable not found.")
    hdx_processor = CountryProcessor(config_json, language_json)
    task_ids = hdx_processor.init_call(
        iso3=args.iso3,
        ids=args.ids,
        fetch_scheduled_exports=args.fetch_scheduled_exports,
    )
    if args.track:
        hdx_processor.track_tasks_status(task_ids)


if __name__ == "__main__":
    main()
