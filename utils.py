from urllib.parse import quote

import requests


def get_available_features(raw_data_api_base_url, skip=0, limit=300):
    response_comb = []
    while True:
        hdx_api_url = f"{raw_data_api_base_url}/cron/?skip={skip}&limit={limit}"
        response = requests.get(hdx_api_url)
        response.raise_for_status()
        if not response.json():
            break  # Break the loop for an empty response
        response_comb.extend(response.json())
        skip = limit
        limit += 100
    return response_comb


def fetch_last_run_info(api_base_url, folder_path):
    try:
        meta_endpoint = f"/s3/get/{quote(folder_path)}"
        response = requests.get(f"{api_base_url}{meta_endpoint}")
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as err:
        print(err)
        return None
