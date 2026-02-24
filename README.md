# arm-doc-index

This is the arm index tool that allows indexing and downloading of arm downloadables.

## Pre-requisites

- Python 3.13 or newer
- **Svn**: The Subversion command-line client is required *only if* you intend to use the `svn` connector.

## Installation

Create a virtual environment

```bash
python3.13 -m venv .
source bin/activate
```

Install armdocindex

```bash
pip3 install git+https://gitlab.prod.spe.aws.arm.com/peg-infra/arm-doc-index
```

## Usage

### First Run and Configuration

The first time you run the tool, it will automatically create a default configuration file at `~/.config/arm-index/config.ini`. This file is essential for telling the tool which data source to index.

You must edit this file to select and configure a data source.

### Configuring the Data Source

Open the configuration file located at `~/.config/arm-index/config.ini`. You will see a `[SOURCE]` section with two keys: `type` and `url`.

-   **`type`**: Can be `svn` or `web`. This determines which connector the tool will use.
-   **`url`**: The endpoint for the selected connector.

#### Example 1: Using the SVN Connector

To index an SVN repository, set the `type` to `svn` and provide the repository URL.

```ini
[SOURCE]
type = svn
url = https://cam-svn2.cambridge.arm.com/svn/asd/support/training_material/
```

#### Example 2: Using the Web (API) Connector

To index the official Arm Developer documentation, set the `type` to `web` and provide the API endpoint URL.

```ini
[SOURCE]
type = web
url = https://documentation-service.arm.com/documentation/
```
#### Example 3: Using the Learn Connector

To index Arm Learning Paths (tutorials and install guides), set the `type` to `learn` and provide the website URL.

```ini
[SOURCE]
type = learn
url = https://learn.arm.com
```

#### Example 4: Using the FVP Connector

To index FVP Builds, set the `type` to `fvp` and provide the ssh endpoint.

```ini
[SOURCE]
type = fvp
url = ssh://login2.euhpc.arm.com
```
### Display Configuration
The tool provides several display options that can be configured in the `[DISPLAY]` section of `~/.config/arm-index/config.ini`:

#### Age Filter
By default, the tool only shows documents modified within the last 365 days. You can adjust this by adding a `max_age_days` setting:
```ini
[DISPLAY]
max_age_days = 365
```

Set to a smaller value (e.g, `90` or `30`) to only show more recent documents, or a larger value to include older documents.

### Running the Tool

Once the configuration is set, you can run the tool.

**To start the interactive display:**
(This will use the cached index if it exists, or create a new one on the first run.)

```bash
arm-doc-index
```

**To force a re-index of the data source:**
(This deletes the old database and fetches all data again from the configured source.)

```bash
arm-doc-index --reindex
```

## Support

Arm Slack: #help-spe-infra and tag Tom Pilar

## Roadmap

- Add more backends (sharepoint, developer, learning paths, ...)
- Add more display features (pop-up boxes)
- Add multi OS support

## Authors

Tom Pilar
Gen Hernandez
Raghav Roy

## License

SPDX: BSD-2-Clause

## Project status

Ongoing
