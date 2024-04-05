import json
import os
import webbrowser
from functools import lru_cache

import requests
import streamlit as st

from extract import CountryProcessor
from utils import get_available_features as fetch_hdx_api


@lru_cache(maxsize=None)
def generate_auth_token(raw_data_api_base_url):
    auth_login_url = f"{raw_data_api_base_url}/auth/login"
    response = requests.get(auth_login_url)
    response.raise_for_status()
    login_url = response.json().get("login_url")

    if login_url:
        st.success(
            f"Login link generated [here]({login_url}). Please Log in & Copy Your Token"
        )
        webbrowser.open_new_tab(login_url)
    else:
        st.error(
            "Failed to generate login link. Please check the raw data API base URL."
        )


def main():
    st.title("Country Extractor App")

    default_config_path = "config.json"
    default_config_data = None
    if os.path.exists(default_config_path):
        with open(default_config_path, "r") as f:
            try:
                default_config_data = json.load(f)
            except json.JSONDecodeError:
                st.error(
                    "Error loading default config.json. Please provide a valid JSON configuration or URL."
                )
                return

    raw_data_api_base_url = st.text_input(
        "Enter RAW_DATA_API_BASE_URL (default is https://api-prod.raw-data.hotosm.org/v1):",
        "https://api-prod.raw-data.hotosm.org/v1",
    )
    if "rawdata_api_auth_token" not in st.session_state:
        st.session_state.rawdata_api_auth_token = st.text_input(
            "Enter RAWDATA_API_AUTH_TOKEN:", type="password"
        )
    else:
        st.session_state.rawdata_api_auth_token = st.text_input(
            "Enter RAWDATA_API_AUTH_TOKEN:",
            type="password",
            value=st.session_state.rawdata_api_auth_token,
        )

    rawdata_auth_link = st.button("Generate Raw Data API Auth Token")
    if rawdata_auth_link:
        with st.spinner("Generating auth token..."):
            generate_auth_token(raw_data_api_base_url)

    config_json_input = st.text_area(
        "Enter JSON configuration or URL:",
        value=json.dumps(default_config_data, indent=2) if default_config_data else "",
    )

    try:
        config_data = json.loads(config_json_input)
    except json.JSONDecodeError:
        try:
            response = requests.get(config_json_input)
            response.raise_for_status()
            config_data = response.json()
        except requests.RequestException:
            st.error(
                "Invalid JSON or URL. Please provide a valid JSON configuration or URL."
            )
            return

    show_config_button = st.button("Show Configuration JSON")
    if show_config_button:
        st.json(config_data)

    with st.spinner("Fetching HDX API..."):
        hdx_data = fetch_hdx_api(raw_data_api_base_url)
    iso3_options = sorted(
        [
            (
                option["properties"]["iso3"],
                option["properties"]["dataset"]["dataset_title"],
            )
            for option in hdx_data
            if option["properties"]["iso3"] is not None
        ],
        key=lambda x: x[1],
    )

    hdx_id_options = sorted(
        [
            (
                option["properties"]["id"],
                option["properties"]["dataset"]["dataset_title"],
            )
            for option in hdx_data
        ],
        key=lambda x: x[1],
    )
    selected_iso3 = st.multiselect(
        "Select ISO3 options:", iso3_options, format_func=lambda x: f"{x[0]} - {x[1]}"
    )

    selected_hdx_ids = st.multiselect(
        "Select HDX ID options:",
        hdx_id_options,
        format_func=lambda x: f"{x[0]} - {x[1]}",
    )

    fetch_scheduled_exports = st.checkbox("Fetch scheduled exports")
    frequency = None
    if fetch_scheduled_exports:
        frequency = st.text_input(
            "Enter frequency for fetching scheduled exports (default is daily):",
            "daily",
        )

    track = st.checkbox("Track task status")

    extraction_in_progress = False

    extraction_button_key = "extraction_button"
    extraction_button_label = "Run Extraction"
    if extraction_in_progress:
        extraction_button_label = "Extraction in Progress..."
    elif st.button(extraction_button_label, key=extraction_button_key):
        extraction_in_progress = True
        spinner = st.spinner("Extracting... Please wait.")
        with spinner:
            hdx_processor = CountryProcessor(config_data)

            hdx_processor.RAW_DATA_API_BASE_URL = raw_data_api_base_url
            hdx_processor.RAWDATA_API_AUTH_TOKEN = (
                st.session_state.rawdata_api_auth_token
            )

            selected_iso3_values = [iso3 for iso3, _ in selected_iso3]
            selected_hdx_ids_values = [ids for ids, _ in selected_hdx_ids]
            task_ids = hdx_processor.init_call(
                iso3=selected_iso3_values,
                ids=selected_hdx_ids_values,
                fetch_scheduled_exports=frequency,
            )

            if (
                not selected_iso3
                and not selected_hdx_ids
                and not fetch_scheduled_exports
            ):
                st.warning(
                    "Please select country ISO3 codes or HDX export IDs or enable 'Fetch scheduled exports', but not all three."
                )

            if track:
                hdx_processor.track_tasks_status(task_ids)

                result_file_path = os.path.join(os.getcwd(), "result.json")
                if os.path.exists(result_file_path):
                    with open(result_file_path, "r") as result_file:
                        result_data = json.load(result_file)
                    st.subheader("Task Status Results:")
                    st.json(result_data)

                    # Add a download button for result.json
                    st.download_button(
                        label="Download result.json",
                        data=json.dumps(result_data, indent=2),
                        file_name="result.json",
                        key="result_json_download",
                    )
                else:
                    st.warning("Result file not found.")
            st.success(f"Extraction Completed. Task IDs: {task_ids}")
            extraction_in_progress = False


if __name__ == "__main__":
    main()
