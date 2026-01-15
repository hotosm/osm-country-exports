# Humanitarian Data Exchange <> HOTOSM

- We manage **monthly** country exports on the humanitarian data exchange.
- The exports contain all OSM data deemed beneficial for Humanitarian action,
  defined here: https://github.com/hotosm/osm-country-exports/blob/main/config.yaml
- They are exported as separate datasets, e.g. buildings, roads, waterways, etc.
  - Congo populated places: https://data.humdata.org/dataset/hotosm_cog_populated_places
  - Ecuador populated placed: https://data.humdata.org/dataset/hotosm_ecu_waterways
- The exports are done in formats:
  - Shapefile
  - Geopackage
  - Geojson
  - KML
- Data is stored in S3.

## How export jobs are stored

There are two ways the exports are triggered:
1. Stored in the `cron` table of raw-data-api:
  - They are defined in advance here in the database: https://github.com/hotosm/raw-data-api/blob/develop/API/data/cron.sql
  - Go to https://api-prod.raw-data.hotosm.org/v1/cron/?limit=1000 to see the active cronjobs.
  - Every 5 mins the system is scanned and active cron exports are executed.
  - I'm not 100% certain this system is operating (could be wrong), hence why we use option 2 below.
2. The exports can be triggered `ondemand` via API call to raw-data-api:
  - We have a script that scans through the export options available in the raw-data-api cron table (all countries of world):
    https://github.com/hotosm/osm-country-exports/blob/main/extract.py
  - The script extracts the cron info, then sends an `ondemand` request to the raw-data-api endpoint `/custom/snapshot/`.
  - There are three Github actions that can be used to trigger an export of every country, at different frequencies:
    - https://github.com/hotosm/osm-country-exports/actions/workflows/run_monthly.yml (always active)
    - https://github.com/hotosm/osm-country-exports/actions/workflows/run_weekly.yml (enabled as needed)
    - https://github.com/hotosm/osm-country-exports/actions/workflows/run_daily.yml (enabled as needed)

## How the exports are uploaded to HDX

- The crons table has a key `hdx_upload=True` for all datasets that are uploaded to HDX.
- For country exports defined in the `cron` table, the datasets are **updated** in the
  existing HDX dataset listing (e.g. rwanda buildings).
- Setting this param to true creates a dataset with predefined params:
    ```
        Dataset name format: {dataset_prefix}_{category_name}
        Title format: {dataset_title} {category_name} (OpenStreetMap Export)
        License: ODC-ODBL
        Source: OpenStreetMap contributors
    ```
- HDX vars are configured as part of raw-data-api deployment:
    ```toml
    [HDX]  
    ENABLE_HDX_EXPORTS = True  
    HDX_SITE = demo  # or 'prod' for production
    HDX_API_KEY = your_api_key  
    HDX_OWNER_ORG = your_organization_id  
    HDX_MAINTAINER = your_maintainer_id
    ```
- This uses a HDX API Key defined in AWS secrets, injected into the Python exports
  that run on raw-data-api hosted there.

### Updating the HDX API Key

- The key expires annually I think?
- An email notification will be sent prior to expiry.
- Be sure to update the AWS secret with the new key, as needed.

## Modifying the export frequency

### Via UI

- A simple way to do this via a UI is: https://oce-extract.streamlit.app/
- The `cron` table could have a PATCH request for the `update_frequency` param:
  - 'weekly'
  - 'monthly'
  - 'daily'
  - 'as needed'

### Via Github actions

- Enable the Github action for weekly or daily to update the frequency.

