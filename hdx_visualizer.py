from datetime import datetime
from urllib.parse import quote

import humanize
import requests
import streamlit as st
from streamlit_tree_select import tree_select


def fetch_hdx_api(raw_data_api_base_url, skip=0, limit=100):
    response_comb = []
    while True:
        hdx_api_url = f"{raw_data_api_base_url}/hdx/?skip={skip}&limit={limit}"
        response = requests.get(hdx_api_url)
        response.raise_for_status()
        if not response.json():
            break  # Break the loop for an empty response
        response_comb.extend(response.json())
        skip = limit
        limit += 100
    return response_comb


def get_available_features(api_base_url):
    return fetch_hdx_api(api_base_url)


def transform_to_tree_structure(data):
    tree_structure = {}
    for item in data:
        folders = item["Key"].split("/")
        current_level = tree_structure
        for folder in folders:
            current_level = current_level.setdefault(folder, {})
    return tree_structure


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


def fetch_last_run_info(api_base_url, folder_path):
    meta_endpoint = f"/s3/get/{quote(folder_path)}"
    response = requests.get(f"{api_base_url}{meta_endpoint}")
    return response.json()


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


def visualize_summary(last_run, hdx_upload_summary, hdx_datasets_summary):
    st.sidebar.title("Summary")
    st.sidebar.write(
        f"**Last run:** {humanize.naturaldate(datetime.strptime(last_run['Last run'], '%Y-%m-%dT%H:%M:%S.%f'))} | "
        f"**Processing time:** {last_run['Processing time']} | "
        f"**HDX Upload:**  Total : {last_run['Total datasets']} , Success: {hdx_upload_summary['SUCCESS']}, Failed: {hdx_upload_summary['FAILED']}, Skipped: {hdx_upload_summary['SKIPPED']}"
    )

    st.sidebar.subheader("Datasets:")
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


def download_file(api_base_url, key):
    return f"{api_base_url}/s3/get/{quote(key)}"


def visualize_data(api_base_url, selected_features):
    for feature in selected_features:
        iso3 = feature["properties"].get("iso3")
        dataset_folder = feature["properties"]["dataset"]["dataset_folder"]
        dataset_prefix = feature["properties"]["dataset"]["dataset_prefix"]

        st.subheader(f"Exports for {iso3 or dataset_prefix}")

        folder_path = (
            f"{dataset_folder}/{iso3}/"
            if iso3
            else f"{dataset_folder}/{dataset_prefix}/"
        )
        endpoint = f"/s3/files/?folder={quote(folder_path)}"
        response = requests.get(f"{api_base_url}{endpoint}")
        data = response.json()

        if not data:
            st.warning("No data available for visualization.")
            continue
        tree_structure = transform_to_tree_structure(data)
        visualize_folder_structure(api_base_url, tree_structure, data)

        # Fetch and display last run info
        last_run_info = fetch_last_run_info(api_base_url, f"{folder_path}/meta.json")
        # st.sidebar.subheader("Meta:")
        last_run_summary, hdx_upload_summary, hdx_datasets_summary = generate_summary(
            last_run_info
        )
        visualize_summary(last_run_summary, hdx_upload_summary, hdx_datasets_summary)


def main():
    st.title("Country Exports")
    raw_data_api_base_url = st.text_input(
        "Enter RAW_DATA_API_BASE_URL:", "https://api-prod.raw-data.hotosm.org/v1"
    )

    available_features = get_available_features(raw_data_api_base_url)
    selected_feature_indices = st.selectbox(
        "Select countries to fetch:",
        range(len(available_features)),
        format_func=lambda i: f"{available_features[i]['properties']['id']} - {available_features[i]['properties']['dataset']['dataset_title']}",
    )

    selected_features = [available_features[selected_feature_indices]]

    visualize_data(raw_data_api_base_url, selected_features)


if __name__ == "__main__":
    main()
