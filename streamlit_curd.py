import json
import webbrowser

import geopandas as gpd
import humanize
import matplotlib.pyplot as plt
import requests
import streamlit as st

from utils import fetch_last_run_info, get_available_features


# Helper function to send HTTP requests
@st.cache_data
def send_request(method, url, data=None, headers=None):
    if method == "GET":
        response = requests.get(url, headers=headers)
    elif method == "POST":
        response = requests.post(url, json=data, headers=headers)
    elif method == "PUT":
        response = requests.put(url, json=data, headers=headers)
    elif method == "PATCH":
        response = requests.patch(url, json=data, headers=headers)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)

    return response.json()


# CRUD operation functions
@st.cache_data
def create_hdx(data, base_url, access_token):
    url = f"{base_url}/hdx/"
    headers = {"Access-Token": access_token}

    return send_request("POST", url, data=data, headers=headers)


@st.cache_data
def read_hdx(hdx_id=None, base_url=None, access_token=None):
    if hdx_id:
        url = f"{base_url}/hdx/{hdx_id}"
    else:
        url = f"{base_url}/hdx/"
    headers = {"Access-Token": access_token}
    return send_request("GET", url, headers=headers)


@st.cache_data
def update_hdx(hdx_id, data, base_url, access_token):
    url = f"{base_url}/hdx/{hdx_id}"
    headers = {"Access-Token": access_token}
    return send_request("PATCH", url, data=data, headers=headers)


@st.cache_data
def get_country_geojson(base_url, access_token, cid):
    url = f"{base_url}/countries/{cid}/"
    headers = {"Access-Token": access_token}
    return send_request("GET", url, headers=headers)


# Function to generate auth token
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


# Input API URL and authentication
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
    generate_auth_token(raw_data_api_base_url)

# Get available HDX layers
with st.spinner("Loading available HDX layers..."):
    hdx_layers = get_available_features(raw_data_api_base_url=raw_data_api_base_url)
hdx_layer_titles = [
    f"{layer['properties']['id']} - {layer['properties']['dataset']['dataset_title']}"
    for layer in hdx_layers
]
selected_layer_title = st.sidebar.selectbox(
    "Select HDX Layer", hdx_layer_titles, key="select_layer"
)

if selected_layer_title:
    selected_layer_id = int(selected_layer_title.split(" - ")[0])

    # Read selected layer details
    with st.spinner("Loading layer details..."):
        selected_layer = read_hdx(
            selected_layer_id,
            base_url=raw_data_api_base_url,
            access_token=st.session_state.rawdata_api_auth_token,
        )

    # Display layer details
    st.write(f"Layer ID: {selected_layer['properties']['id']}")
    st.write(f"Layer Title: {selected_layer['properties']['dataset']['dataset_title']}")

    folder_path = (
        f"{selected_layer['properties']['dataset'].get('dataset_folder')}/{selected_layer['properties'].get('iso3')}/"
        if selected_layer["properties"].get("iso3")
        else f"{selected_layer['properties']['dataset'].get('dataset_folder')}/{selected_layer['properties']['dataset'].get('dataset_prefix')}/"
    )
    last_run_info = fetch_last_run_info(
        raw_data_api_base_url, f"{folder_path}meta.json"
    )
    st.write(
        "Last Run Date: ",
        (
            humanize.naturaldate(last_run_info.get("started_at", "N/A"))
            if last_run_info
            else "N/A"
        ),
    )
    st.write(
        "Elapsed time : ",
        last_run_info.get("elapsed_time", "N/A") if last_run_info else "N/A",
    )

    # Visualize geometry on a map
    if selected_layer["geometry"]["type"] is None and selected_layer["properties"].get(
        "cid"
    ):
        with st.spinner("Loading country geometry..."):
            country_geojson = get_country_geojson(
                raw_data_api_base_url,
                st.session_state.rawdata_api_auth_token,
                selected_layer["properties"]["cid"],
            )
        gdf = gpd.GeoDataFrame.from_features(
            {"type": "FeatureCollection", "features": [country_geojson]}, crs="4326"
        )
        fig, ax = plt.subplots(figsize=(8, 8))
        gdf.plot(ax=ax, edgecolor="red", facecolor="none")
        st.pyplot(fig)

    elif selected_layer["geometry"]["type"] is not None:
        geometry = json.loads(selected_layer["geometry"])
        gdf = gpd.GeoDataFrame.from_features(geometry, crs="4326")
        fig, ax = plt.subplots(figsize=(8, 8))
        gdf.plot(ax=ax, edgecolor="red", facecolor="none")
        st.pyplot(fig)

    # Update layer fields interactively
    st.write("Update Layer Fields:")
    updated_fields = {}

    # Update iso3, cid, and queue
    for key in ["iso3", "cid", "queue"]:
        value = selected_layer["properties"].get(key)
        updated_value = st.text_input(f"{key}", value=str(value))
        if updated_value != str(value):
            updated_fields[key] = updated_value

    # Update hdx_upload and meta
    for key in ["hdx_upload", "meta"]:
        value = selected_layer["properties"].get(key)
        updated_value = st.checkbox(f"{key}", value=value)
        if updated_value != value:
            updated_fields[key] = updated_value

    # Update dataset
    current_dataset = selected_layer["properties"].get("dataset", {})
    dataset_title = st.text_input(
        "Dataset Title", value=current_dataset.get("dataset_title", "")
    )
    dataset_folder = st.text_input(
        "Dataset Folder", value=current_dataset.get("dataset_folder", "")
    )
    dataset_prefix = st.text_input(
        "Dataset Prefix", value=current_dataset.get("dataset_prefix", "")
    )
    update_frequency = st.selectbox(
        "Update Frequency",
        ["daily", "weekly", "monthly", "disabled"],
        index=["daily", "weekly", "monthly", "disabled"].index(
            current_dataset.get("update_frequency", "monthly")
        ),
    )
    dataset_locations = st.text_input(
        "Dataset Locations", current_dataset.get("dataset_locations", [])
    )
    updated_dataset = {
        "dataset_title": dataset_title,
        "dataset_folder": dataset_folder,
        "dataset_prefix": dataset_prefix,
        "update_frequency": update_frequency,
        "dataset_locations": dataset_locations,
    }
    if updated_dataset != current_dataset:
        updated_fields["dataset"] = updated_dataset

    # Update categories
    current_categories = selected_layer["properties"].get("categories", {})
    updated_categories = st.text_area(
        "Categories", value=json.dumps(current_categories, indent=4)
    )
    if updated_categories != json.dumps(current_categories, indent=4):
        updated_fields["categories"] = json.loads(updated_categories)

    current_geometry = selected_layer["properties"].get("geometry")
    updated_geometry = st.text_area(
        "Geometry", value=json.dumps(current_geometry, indent=4)
    )
    if updated_geometry != json.dumps(current_geometry, indent=4):
        updated_fields["geometry"] = json.loads(updated_geometry)


if st.button("Save Updates"):
    with st.spinner("Updating layer..."):
        response = update_hdx(
            selected_layer_id,
            updated_fields,
            base_url=raw_data_api_base_url,
            access_token=st.session_state.rawdata_api_auth_token,
        )
    st.write(response)

# Create a new HDX layer
st.sidebar.title("Create New HDX Layer")
new_layer_data = {}
new_layer_data["iso3"] = st.sidebar.text_input("ISO3")
new_layer_data["hdx_upload"] = st.sidebar.checkbox("HDX Upload", value=True)
dataset_title = st.sidebar.text_input("Dataset Title")
dataset_folder = st.sidebar.text_input("Dataset Folder")
dataset_prefix = st.sidebar.text_input("Dataset Prefix")
update_frequency = st.sidebar.selectbox(
    "Update Frequency", ["daily", "weekly", "monthly"], index=1
)
dataset_locations = st.sidebar.text_input("Dataset Locations", [])
new_layer_data["dataset"] = {
    "dataset_title": dataset_title,
    "dataset_folder": dataset_folder,
    "dataset_prefix": dataset_prefix,
    "update_frequency": update_frequency,
    "dataset_locations": dataset_locations,
}
new_layer_data["queue"] = st.sidebar.text_input("Queue", value="raw_ondemand")
new_layer_data["meta"] = st.sidebar.checkbox("Meta", value=False)
new_layer_data["categories"] = st.sidebar.text_area("Categories", value="{}")
new_layer_data["geometry"] = st.sidebar.text_area("Geometry")

if st.sidebar.button("Create Layer"):
    with st.spinner("Creating new layer..."):
        response = create_hdx(
            new_layer_data,
            base_url=raw_data_api_base_url,
            access_token=st.session_state.rawdata_api_auth_token,
        )
    st.sidebar.write(response)
