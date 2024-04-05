import concurrent.futures
from datetime import datetime
from urllib.parse import quote

import humanize
import pandas as pd
import requests
import streamlit as st

from utils import fetch_last_run_info, get_available_features


@st.cache_data
def transform_to_tree_structure(data):
    tree_structure = {}
    for item in data:
        folders = item["Key"].split("/")
        current_level = tree_structure
        for folder in folders:
            current_level = current_level.setdefault(folder, {})
    return tree_structure


@st.cache_data
def convert_to_collapsible_lists(api_base_url, tree_structure, data, parent_label=""):
    lists = []
    for key, value in tree_structure.items():
        label = f"{parent_label}/{key}" if parent_label else key
        list_content = []

        total_size, last_modified_date = calculate_selected_size_and_date([label], data)
        formatted_date = (
            humanize.naturaldate(last_modified_date) if last_modified_date else "N/A"
        )
        list_content.append(
            f"<i><small>Size: {humanize.naturalsize(total_size)}</small></i>"
        )
        list_content.append(f"<i><small>Last Modified: {formatted_date}</small></i>")

        # Add a tiny download button for .zip files
        if label.endswith(".zip") or label.endswith(".json"):
            download_link = download_file(api_base_url, label)
            list_content.append(
                f'<a href="{download_link}" target="_blank"><button style="font-size: 10px; padding: 2px 2px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer;">Download</button></a>'
            )

        if isinstance(value, dict):
            children_lists = convert_to_collapsible_lists(
                api_base_url, value, data, label
            )
            list_content.extend(children_lists)
        lists.append({"label": label, "content": list_content})

    return lists


@st.cache_data
def visualize_folder_structure(api_base_url, tree_structure, data):
    def build_html_recursive(item):
        html = "<ul>"
        for entry in item:
            if isinstance(entry, dict):
                label = entry["label"]
                content = entry["content"]

                html += f"<li><details><summary><b>{label}</b></summary><ul>"
                if isinstance(content, list):
                    html += build_html_recursive(content)
                html += "</ul></details></li>"
            else:
                html += f" {entry}"

        html += "</ul>"
        return html

    collapsible_lists = convert_to_collapsible_lists(api_base_url, tree_structure, data)
    for collapsible_list in collapsible_lists:
        label = collapsible_list["label"]
        content = collapsible_list["content"]

        html = build_html_recursive(content)
        st.markdown(
            f"<details><summary><b>{label}</b></summary>{html}</details>",
            unsafe_allow_html=True,
        )


@st.cache_data
def visualize_summary(last_run, hdx_upload_summary, hdx_datasets_summary):
    st.sidebar.title("Summary")
    st.sidebar.write(
        f"**Last run:** {humanize.naturaldate(datetime.strptime(last_run['Last run'], '%Y-%m-%dT%H:%M:%S.%f'))} | "
        f"**Processing time:** {last_run['Processing time']} | "
        f"**Upload:**  Total : {last_run['Total datasets']} , Success: {hdx_upload_summary['SUCCESS']}, Failed: {hdx_upload_summary['FAILED']}, Skipped: {hdx_upload_summary['SKIPPED']}"
    )

    st.sidebar.subheader("HDX Datasets:")
    for dataset_summary in hdx_datasets_summary:
        category_name = dataset_summary["category"]
        st.sidebar.markdown(
            f"<details><summary><a href='{dataset_summary['hdx_url']}' style='font-size: 16px; text-decoration: none; color: #0366d6;'>{category_name}</a></summary>"
            f"<ul>"
            f"<li><b>Name:</b> {dataset_summary['name']}</li>"
            f"<li><b>Resources:</b> {dataset_summary['resources']}</li>"
            f"<li><b>Total Size:</b> {humanize.naturalsize(dataset_summary['total_size'])}</li>"
            f"<li><b>Formats:</b> {', '.join(f'{format_name} ({count})' for format_name, count in dataset_summary['formats'].items())}</li>"
            f"</ul>"
            f"</details>",
            unsafe_allow_html=True,
        )


@st.cache_data
def calculate_selected_size_and_date(selected_items, data):
    total_size = 0
    last_modified_dates = []

    for item in data:
        for folder_path in selected_items:
            if item["Key"].startswith(folder_path):
                total_size += item.get("Size", 0)
                last_modified_date_str = item.get("LastModified")
                if last_modified_date_str:
                    # Convert the date string to a datetime object
                    last_modified_date = datetime.strptime(
                        last_modified_date_str, "%Y-%m-%dT%H:%M:%SZ"
                    )
                    last_modified_dates.append(last_modified_date)

    latest_last_modified_date = max(last_modified_dates, default=None)
    return total_size, latest_last_modified_date


@st.cache_data
def process_feature(feature, api_base_url):
    properties = feature["properties"]
    dataset_info = properties.get("dataset", {})
    iso3 = properties.get("iso3")
    dataset_folder = dataset_info.get("dataset_folder")
    dataset_prefix = dataset_info.get("dataset_prefix")

    folder_path = (
        f"{dataset_folder}/{iso3}/" if iso3 else f"{dataset_folder}/{dataset_prefix}/"
    )
    last_run_info = fetch_last_run_info(api_base_url, f"{folder_path}meta.json")

    record = {
        "ID": properties.get("id"),
        "ISO3": iso3,
        # "CID": properties.get("cid"),
        "Dataset Title": dataset_info.get("dataset_title"),
        "HDX Upload": properties.get("hdx_upload"),
        # "Dataset Folder": dataset_folder,
        "Dataset Prefix": dataset_prefix,
        "Update Frequency": dataset_info.get("update_frequency"),
        "Elapsed Time": (
            last_run_info.get("elapsed_time", "N/A") if last_run_info else "N/A"
        ),
        "Last Run Date": (
            last_run_info.get("started_at", "N/A") if last_run_info else "N/A"
        ),
    }
    return record


@st.cache_data
def all_hdx_table(data, api_base_url, progress_bar):
    records = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_feature = {
            executor.submit(process_feature, feature, api_base_url): feature
            for feature in data
        }

        for i, future in enumerate(concurrent.futures.as_completed(future_to_feature)):
            record = future.result()
            records.append(record)
            # Update the progress bar
            progress_bar.progress((i + 1) / len(data))

    return pd.DataFrame(records)


@st.cache_data
def generate_summary(meta_data):
    last_run = {
        "Last run": meta_data.get("started_at"),
        "Total datasets": len(meta_data.get("datasets", [])),
        "Processing time": meta_data.get("elapsed_time"),
    }

    hdx_upload_summary = {"SUCCESS": 0, "FAILED": 0, "SKIPPED": 0}
    hdx_datasets_summary = []

    for dataset_entry in meta_data.get("datasets", []):
        for category_name, dataset in dataset_entry.items():
            hdx_upload_status = dataset.get("hdx_upload", "SKIPPED")
            hdx_upload_summary[hdx_upload_status] += 1

            dataset_summary = {
                "category": category_name,
                "name": dataset.get("name"),
                "resources": len(dataset.get("resources", [])),
                "total_size": sum(
                    res.get("size", 0) for res in dataset.get("resources", [])
                ),
                "formats": {
                    res.get("format", ""): 1 for res in dataset.get("resources", [])
                },
                "hdx_url": dataset.get("hdx_url"),
            }

            hdx_datasets_summary.append(dataset_summary)

    return last_run, hdx_upload_summary, hdx_datasets_summary


@st.cache_data
def download_file(api_base_url, key):
    return f"{api_base_url}/s3/get/{quote(key)}"


def visualize_data(api_base_url, selected_features):
    for feature in selected_features:
        iso3 = feature["properties"].get("iso3")
        dataset_folder = feature["properties"]["dataset"]["dataset_folder"]
        dataset_prefix = feature["properties"]["dataset"]["dataset_prefix"]
        dataset_frequency = feature["properties"]["dataset"]["update_frequency"]

        st.subheader(f"Exports for {iso3 or dataset_prefix}")
        st.write("Update Frequency:", dataset_frequency)

        folder_path = (
            f"{dataset_folder}/{iso3}/"
            if iso3
            else f"{dataset_folder}/{dataset_prefix}/"
        )
        endpoint = f"/s3/files/?folder={quote(folder_path)}"

        with st.spinner(f"Loading data for {iso3 or dataset_prefix}..."):
            response = requests.get(f"{api_base_url}{endpoint}")
            data = response.json()

        if not data:
            st.warning("No data available.")
            continue

        tree_structure = transform_to_tree_structure(data)
        visualize_folder_structure(api_base_url, tree_structure, data)

        # Fetch and display last run info
        last_run_info = fetch_last_run_info(api_base_url, f"{folder_path}meta.json")
        if last_run_info:
            (
                last_run_summary,
                hdx_upload_summary,
                hdx_datasets_summary,
            ) = generate_summary(last_run_info)
            visualize_summary(
                last_run_summary, hdx_upload_summary, hdx_datasets_summary
            )


def main():
    st.title("Country Exports")
    raw_data_api_base_url = st.text_input(
        "Enter RAW_DATA_API_BASE_URL:", "https://api-prod.raw-data.hotosm.org/v1"
    )

    with st.spinner("Loading available features..."):
        available_features = get_available_features(raw_data_api_base_url)

    df = pd.DataFrame()
    display_all_info = st.checkbox("Display all exports info")
    if display_all_info:
        progress_bar = st.progress(0)
        df = all_hdx_table(available_features, raw_data_api_base_url, progress_bar)
        st.dataframe(df)

    selected_feature_indices = st.selectbox(
        "Select countries to fetch:",
        range(len(available_features)),
        format_func=lambda i: f"{available_features[i]['properties']['id']} - {available_features[i]['properties']['dataset']['dataset_title']}",
    )

    selected_features = [available_features[selected_feature_indices]]

    visualize_data(raw_data_api_base_url, selected_features)


if __name__ == "__main__":
    main()
