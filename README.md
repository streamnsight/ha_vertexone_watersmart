# ha_vertexone_watersmart

Home Assistant Custom Component for VertexOne WaterSmart

## How to install

- Copy the `vertexone_watersmart` folder into you `config/custom_components` folder.

- Restart Home Assistant

- Go to Settings -> Devices & Services

- Click Add Integration

- Search for watersmart in the list

- Click the VertexOne WaterSmart integration

- You will be prompted for the name of your utility provider, and your credentials for the watersmart portal (Typically your username (email) and password)

- Note it may take a few minutes to get initialized as the first time the integration is added, a full year worth of historical data is being populated.

## Can't find your provider?

There is no API to fetch the full list of providers. They are hard-coded in the api python package [https://github.com/streamnsight/vertexone-watersmart](https://github.com/streamnsight/vertexone-watersmart)

Please submit an issue in that repository to add your provider.