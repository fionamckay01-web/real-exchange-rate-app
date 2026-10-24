# IMF Real Exchange Rate Explorer

A Streamlit app that compares nominal and real exchange rates between two
economies using monthly IMF data.

The app is designed for Python 3.12.

## What the app does

Users can:

- Choose Country 1 and Country 2, including the Euro area.
- Retrieve monthly IMF CPI and exchange-rate data from January 1976 where
  available.
- Select a start and end month.
- View the Real Index, Nominal exchange rate, or Both.
- View Real and Nominal series on separate y-axes when Both is selected.
- Download all observations and calculations in the selected sample as CSV.

## Economic definitions

The assignment defines:

- `S(t)` = units of Country 2 currency per one unit of Country 1 currency
- `P1(t)` = Country 1 CPI
- `P2(t)` = Country 2 CPI

The real exchange rate is:

```text
RER(t) = S(t) × P1(t) / P2(t)
```

For the selected start and end months:

```text
RER* = average of RER(t) over valid months in the selected sample
```

The plotted real exchange-rate index is:

```text
Real Index(t) = 100 × RER(t) / RER*
```

Because `RER*` is calculated from the currently selected sample, changing the
start or end month automatically changes the normalization.

## IMF data

Base API:

```text
https://api.imf.org/external/sdmx/3.0
```

The app uses the current IMF Statistics Department dataflows:

- CPI dataflow: `IMF.STA/CPI`
- Exchange Rates dataflow: `IMF.STA/ER`

Series keys:

```text
CPI:           {ISO3}.CPI._T.IX.M
Exchange rate: {ISO3}.XDC_USD.PA_RT.M
```

The IMF code supplied for the Euro area is:

```text
G163
```

The app requests observations from January 1976 onward when available.

### Exchange-rate direction

The IMF exchange-rate series is expressed as:

```text
local currency units per USD
```

Let:

```text
FX1(t) = Country 1 local currency per USD
FX2(t) = Country 2 local currency per USD
```

The assignment instead requires:

```text
S(t) = Country 2 currency per Country 1 currency
```

Therefore the app converts the IMF rates using:

```text
S(t) = FX2(t) / FX1(t)
```

Example:

If Country 1 is the United Kingdom and Country 2 is the United States, and:

```text
FX_GBR = 0.80 GBP per USD
FX_USA = 1.00 USD per USD
```

then:

```text
S = 1.00 / 0.80 = 1.25 USD per GBP
```

The nominal exchange rate is plotted in these actual currency units. It is not
normalized.

## Missing data

IMF series do not all have the same coverage. Some countries have shorter
histories or gaps.

The app therefore:

- uses the observations returned by the IMF;
- does not interpolate missing values;
- calculates nominal `S(t)` only when both exchange-rate observations exist;
- calculates `RER(t)` only when nominal `S(t)` and both CPI observations exist;
- calculates `RER*` using valid RER observations only.

The CSV retains missing observations so data availability is transparent.

## Files

The repository contains:

```text
app.py
requirements.txt
README.md
```

## Run locally

### 1. Install Python 3.12

Confirm your Python version:

```bash
python --version
```

### 2. Clone or download the repository

Open a terminal in the project folder.

### 3. Optional: create a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the app

```bash
streamlit run app.py
```

Streamlit will display a local URL, normally:

```text
http://localhost:8501
```

Open that address in your browser.

## Suggested checks before submitting

### United Kingdom → United States

Set:

```text
Country 1 = United Kingdom
Country 2 = United States
```

The nominal series should be USD per GBP.

### United States → Japan

Set:

```text
Country 1 = United States
Country 2 = Japan
```

The nominal series should be JPY per USD.

This is a useful direction check because a recent USD/JPY observation should
have the scale of yen per dollar rather than dollars per yen.

### Date-range test

Change the start and end months. Confirm that:

1. `RER*` changes.
2. The Real Index is re-normalized around a sample average of 100.
3. The nominal exchange rate itself does not change normalization.

### CSV test

Download the CSV and confirm it includes:

```text
Date
CPI_<Country1 code>
CPI_<Country2 code>
FX_<Country1 code>_LCU_per_USD
FX_<Country2 code>_LCU_per_USD
Nominal_S
RER
RER_star
Real_Index
```

## Upload to GitHub

Create a GitHub repository, then upload:

```text
app.py
requirements.txt
README.md
```

You can upload them directly through GitHub using:

**Add file → Upload files**

or use Git from a terminal.

## Deploy with Streamlit Community Cloud

1. Push the three files to GitHub.
2. Go to Streamlit Community Cloud.
3. Sign in with GitHub.
4. Choose **Create app**.
5. Select your repository.
6. Set the main file path to:

```text
app.py
```

7. Deploy.

Streamlit will install the packages in `requirements.txt` automatically.

## Notes

- Country choices are generated from ISO-3166 alpha-3 codes using `pycountry`,
  with the IMF Euro-area aggregate (`G163`) added explicitly.
- Some selectable jurisdictions may not have the required IMF series. The app
  reports missing-data cases rather than fabricating observations.
- The app caches IMF requests for 24 hours to reduce repeated API calls.
