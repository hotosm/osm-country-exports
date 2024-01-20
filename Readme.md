## HDX Extractor 

The **HDX Extractor** script is designed to trigger extraction requests for countries which will be later pushed to [HDX platform](https://data.humdata.org/). It utilizes Raw Data API for data extraction. For more complex queries navigate to [osm-rawdata module](https://github.com/hotosm/osm-rawdata/)

## Table of Contents
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
  - [Command Line](#command-line)
  - [AWS Lambda](#aws-lambda)
  - [Streamlit APP](#streamlit)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Config JSON](#config-json)
- [Script Overview](#script-overview)
- [Result Path](#result-path)

## Getting Started

### Prerequisites

- Python 3.x
- Access token for Raw Data API

### Installation
Make sure you have python3 installed on your system
    
- Clone the repository and cd 

```bash
git clone https://github.com/kshitijrajsharma/hdx-extractor
cd hdx-extractor
```

## Usage

### Command Line

Head over to [Env](#environment-variables) to verify you have setup correct env variables & Run the script from the command line with the following options:

- For Specific Countries : 

```bash
python hdx_extractor.py --iso3 NPL
```

- For fetching scheduled exports daily

```bash
python hdx_extractor.py --fetch-scheduled-exports daily
```

- For tracking request and Dumping result

```bash
python hdx_extractor.py --iso3 NPL --track
```

You can set it up as systemd service or cronjob in your PC if required or run manually.

### AWS Lambda

1. **Create an AWS Lambda Function:**

   - In the AWS Management Console, navigate to the Lambda service, Choose role and create one with necessary permissions 

2. **Set Environment Variables:**

   - Add the following environment variables to your Lambda function configuration:

     - `CONFIG_JSON`: Path to the config JSON file. Default is `config.json`.
     - Refer to [Configurations](#configuration) for more env variables as required

3. **Deploy the Script as a Lambda Function:**

   - Zip the contents of your project, excluding virtual environments and unnecessary files (Including config.json)
   - Upload the zip file to your Lambda function.

4. **Configure Lambda Trigger:**

   - Configure an appropriate event source for your Lambda function. This could be an API Gateway, CloudWatch Event, or another trigger depending on your requirements.

5. **Invoke the Lambda Function:**

   - Trigger the Lambda function manually or wait for the configured event source to invoke it.

   Your Lambda function should be able to execute the script with the provided configurations.

### Streamlit

You can run streamlit app to use frontend 

1. Run Locally 
```bash
pip install streamlit
streamlit run streamlit_app.py
```
2. To Use hosted Service :  Go to [tm-extractor.streamlit.app](https://hdx-extractor.streamlit.app/) 

## Configuration

### Environment Variables

Set the following environment variables for proper configuration:

Example : 
```bash
export RAWDATA_API_AUTH_TOKEN='my_token'
```

- **`RAWDATA_API_AUTH_TOKEN`**: API token for Raw Data API authentication, Request admins for yours to [RAW DATA API](https://github.com/hotosm/raw-data-api/)

- **`RAW_DATA_API_BASE_URL`**: Base URL for the Raw Data API. Default is `https://api-prod.raw-data.hotosm.org/v1`.

- **`CONFIG_JSON`**: Path to the config JSON file. Default is `config.json`.

### Config JSON

The `config.json` file contains configuration settings for the extraction process. It includes details about the dataset, categories, and geometry of the extraction area.

```json
{
    "geometry": {...},
    "dataset": {...},
    "categories": [...]
}
```

### Explanation

#### `iso3`
Defines iso3 for the hdx extraction. Only those which are preprovided from the database are supported. With iso3 you don't need to supply dataset_name, title and locations as it will populate them from database table. Use /hdx/ GET api to fetch list.

#### `geometry`
Defines the geographical area for extraction. Typically auto-populated with Custom geometry. Only use if iso3 is not supplied , Enabling geometry will require input of dataset_name, tille , locations compulsarily

#### `queue`
Specifies the Raw Data API queue, often set as "raw_special" for hdx country processing, This can be changed if there is disaster activation and special services are deployed so that those requests can be prioritized.

#### `hdx_upload`
Set this to true for uploading datasets to hdx. if hdx_upload is false then it will produce datasets to s3 but won't push it to hdx.

#### `dataset`
Contains information about the dataset:
- `dataset_prefix`: Prefix for the dataset extraction which will be reflected in hdx page eg : hotosm_npl.
- `dataset_folder`: Default Mother folder to place during extraction eg : HDX , Mindful to change this.
- `dataset_title`: Title of the country export eg : Nepal
- `dataset_locations`: Locations of dataset according to hdx python api , Usually list of iso3 code of country.

#### `categories`
Array of extraction categories, each represented by a dictionary with:
- `Category Name`: Name of the extraction category (e.g., "Buildings", "Roads").
  - `hdx`: Contains `tags` and `caveats` for each catgory eg : tags : ['buildings'] and 'caveats': "Use it carefully , Not verifed'.
  - `types`: Types of geometries to extract (e.g., "polygons", "lines", "points").
  - `select`: Attributes to select during extraction (e.g., "name", "highway", "surface").
  - `where`: Conditions for filtering the data during extraction (e.g., filtering by tags).
  - `formats`: File formats for export (e.g., "geojson", "shp", "kml").

Adjust these settings based on your project requirements and the types of features you want to extract.

Refer to the sample [config.json](./config.json) for default config.


## Script Overview

### Purpose
The script is designed to trigger extraction requests for country exports using the Raw Data API. It automates the extraction process based on predefined configurations.

### Features
- Supports both command line and AWS Lambda execution.
- Dynamically fetches country details using raw data api while enabling custom extraction
- Configurable extraction settings using a `config.json` file.
- Helps debugging the service and track the api requests


## Result Path 

- Your export download link will be generated based on the config , with raw-data-api logic it will be ```Base_download_url```/```dataset_folder```/```dataset_prefix```/```Category_name```/```feature_type```/```dataset_prefix_category_name_export_format.zip```
- Example for Waterways configuration :
Here Category Name is ```Waterways```, dataset_prefix is ```hotosm_cuw```, dataset_folder is ```HDX``` , feature_type is ```lines``` and export format is ```geojson```
s
```json
"a054b170-c403-4fcc-8e6d-6cd63b00a2b2": {
"datasets": [
    {
    "Financial Services": {
        "hdx_upload": "SUCCESS",
        "name": "hotosm_cuw_financial_services",
        "hdx_url": "https://demo.data-humdata-org.ahconu.org/dataset/hotosm_cuw_financial_services",
        "resources": [
        {
            "name": "hotosm_cuw_financial_services_points_shp.zip",
            "url": "https://demo_url/HDX/CUW/financial_services/points/hotosm_cuw_financial_services_points_shp.zip",
            "format": "shp",
            "description": "ESRI Shapefile",
            "size": 1749,
            "last_modifed": "2024-01-20T18:36:01.883360",
            "uploaded_to_hdx": true
        },
        {
            "name": "hotosm_cuw_financial_services_points_kml.zip",
            "url": "https://demo_url/HDX/CUW/financial_services/points/hotosm_cuw_financial_services_points_kml.zip",
            "format": "kml",
            "description": "KML",
            "size": 946,
            "last_modifed": "2024-01-20T18:36:02.124807",
            "uploaded_to_hdx": true
        }
        ]
    }
    },
],
"elapsed_time": "31 seconds",
"started_at": "2024-01-20T18:35:54.966949"
}
```
See [sample result](./sample_result.json) to go through how result will look like
