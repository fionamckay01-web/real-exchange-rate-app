import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import pycountry
import requests
import streamlit as st
from plotly.subplots import make_subplots

# -----------------------------
# App configuration
# -----------------------------
st.set_page_config(
    page_title="IMF Real Exchange Rate Explorer",
    page_icon="🌍",
    layout="wide",
)

IMF_BASE = "https://api.imf.org/external/sdmx/3.0"

# The assignment specifies January 1976 as the earliest requested month.
EARLIEST_MONTH = "1976-01"

# Build a readable country list from ISO-3166 alpha-3 codes and add the
# IMF Euro-area aggregate code supplied in the assignment.
COUNTRY_NAME_TO_CODE = {"Euro area": "G163"}
for country in sorted(pycountry.countries, key=lambda x: x.name):
    COUNTRY_NAME_TO_CODE[country.name] = country.alpha_3

COUNTRY_NAMES = list(COUNTRY_NAME_TO_CODE.keys())


# -----------------------------
# IMF data functions
# -----------------------------
@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def fetch_imf_series(iso3: str, dataflow: str, series_suffix: str) -> pd.DataFrame:
    """
    Fetch one monthly IMF series from the SDMX 3.0 API as CSV.

    Parameters
    ----------
    iso3 : str
        ISO3 country code, or G163 for the Euro area.
    dataflow : str
        IMF dataflow, e.g. "CPI" or "ER".
    series_suffix : str
        Everything after the country code in the SDMX series key.

    Returns
    -------
    DataFrame with columns:
        Date, Value
    """
    key = f"{iso3}.{series_suffix}"
    url = f"{IMF_BASE}/data/dataflow/IMF.STA/{dataflow}/~/{key}"

    # IMF SDMX 3.0 monthly periods use values such as 1976-M01.
    params = {"c[TIME_PERIOD]": "ge:1976-M01"}
    headers = {
        "Accept": "text/csv",
        "User-Agent": "rer-exchange-rate-course-app/1.0",
    }

    response = requests.get(url, params=params, headers=headers, timeout=45)

    if response.status_code == 204 or not response.text.strip():
        return pd.DataFrame(columns=["Date", "Value"])

    response.raise_for_status()

    # If the service returns an HTML or JSON error message despite HTTP 200,
    # avoid passing it to pandas as if it were valid CSV.
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type:
        raise RuntimeError(
            f"IMF returned an unexpected HTML response for {key}. "
            "Please try again later."
        )

    df = pd.read_csv(io.StringIO(response.text), low_memory=False)

    if df.empty:
        return pd.DataFrame(columns=["Date", "Value"])

    # IMF SDMX CSV uses TIME_PERIOD and OBS_VALUE. Keep the checks explicit so
    # an upstream schema change produces a helpful error rather than bad data.
    required = {"TIME_PERIOD", "OBS_VALUE"}
    missing = required.difference(df.columns)
    if missing:
        raise RuntimeError(
            f"Unexpected IMF response for {key}. Missing columns: {sorted(missing)}"
        )

    out = df.loc[:, ["TIME_PERIOD", "OBS_VALUE"]].copy()
    out["OBS_VALUE"] = pd.to_numeric(out["OBS_VALUE"], errors="coerce")

    # IMF monthly dates generally look like "2024-M01".
    cleaned_period = (
        out["TIME_PERIOD"]
        .astype(str)
        .str.replace(r"^(\d{4})-M(\d{2})$", r"\1-\2", regex=True)
    )
    out["Date"] = pd.to_datetime(cleaned_period, errors="coerce")

    out = (
        out.dropna(subset=["Date"])
        .rename(columns={"OBS_VALUE": "Value"})
        .loc[:, ["Date", "Value"]]
        .sort_values("Date")
        .drop_duplicates(subset=["Date"], keep="last")
        .reset_index(drop=True)
    )

    return out


def get_country_data(iso3: str, label: str) -> pd.DataFrame:
    """Fetch CPI and local-currency-per-USD exchange-rate data for one country."""
    cpi = fetch_imf_series(
        iso3=iso3,
        dataflow="CPI",
        series_suffix="CPI._T.IX.M",
    ).rename(columns={"Value": f"{label}_CPI"})

    fx = fetch_imf_series(
        iso3=iso3,
        dataflow="ER",
        series_suffix="XDC_USD.PA_RT.M",
    ).rename(columns={"Value": f"{label}_LCU_per_USD"})

    # USD per USD is exactly 1. The IMF generally carries the U.S. series, but
    # this fallback keeps the calculation usable if that series is unavailable.
    if iso3 == "USA" and fx.empty:
        start = pd.Timestamp(EARLIEST_MONTH)
        end = pd.Timestamp.today().to_period("M").to_timestamp()
        fx = pd.DataFrame(
            {
                "Date": pd.date_range(start=start, end=end, freq="MS"),
                f"{label}_LCU_per_USD": 1.0,
            }
        )

    return pd.merge(cpi, fx, on="Date", how="outer").sort_values("Date")


def build_dataset(code1: str, code2: str) -> pd.DataFrame:
    """
    Build the full pair dataset.

    IMF exchange rates are local-currency units per USD:
        FX1 = Country 1 currency / USD
        FX2 = Country 2 currency / USD

    The assignment defines:
        S = Country 2 currency / Country 1 currency

    Therefore:
        S = FX2 / FX1
    """
    d1 = get_country_data(code1, "Country1")
    d2 = get_country_data(code2, "Country2")

    data = pd.merge(d1, d2, on="Date", how="outer").sort_values("Date")

    data["Nominal_S"] = (
        data["Country2_LCU_per_USD"] / data["Country1_LCU_per_USD"]
    )

    data["RER"] = (
        data["Nominal_S"]
        * data["Country1_CPI"]
        / data["Country2_CPI"]
    )

    # Guard against infinities caused by unexpected zero/missing observations.
    data = data.replace([float("inf"), float("-inf")], pd.NA)

    return data


def month_label(period: pd.Period) -> str:
    return period.strftime("%Y-%m")


# -----------------------------
# App UI
# -----------------------------
st.title("🌍 IMF Real Exchange Rate Explorer")

st.markdown(
    """
Compare the **real** and **nominal** exchange rate between two economies using
monthly IMF CPI and exchange-rate data.

- **S(t)** = units of Country 2 currency per 1 unit of Country 1 currency
- **RER(t)** = S(t) × P1(t) / P2(t)
- **Real Index(t)** = 100 × RER(t) / RER*
- **RER*** = average RER over the currently selected sample
"""
)

with st.sidebar:
    st.header("Controls")

    default_country1 = (
        COUNTRY_NAMES.index("United Kingdom")
        if "United Kingdom" in COUNTRY_NAMES
        else 0
    )
    default_country2 = (
        COUNTRY_NAMES.index("United States")
        if "United States" in COUNTRY_NAMES
        else 0
    )

    country1_name = st.selectbox(
        "Country 1",
        COUNTRY_NAMES,
        index=default_country1,
        help="S(t) will be Country 2 currency units per 1 unit of Country 1 currency.",
    )

    country2_name = st.selectbox(
        "Country 2",
        COUNTRY_NAMES,
        index=default_country2,
    )

    chart_choice = st.radio(
        "Display",
        ["Real", "Nominal", "Both"],
        index=2,
        horizontal=True,
    )

if country1_name == country2_name:
    st.warning(
        "Country 1 and Country 2 are the same. The nominal rate will be 1 and "
        "the real exchange-rate index will be 100 whenever both CPI series are valid."
    )

code1 = COUNTRY_NAME_TO_CODE[country1_name]
code2 = COUNTRY_NAME_TO_CODE[country2_name]

with st.spinner("Retrieving IMF data..."):
    try:
        full_data = build_dataset(code1, code2)
    except requests.RequestException as exc:
        st.error(
            "The IMF API request failed. This can be temporary. "
            f"Technical detail: {exc}"
        )
        st.stop()
    except Exception as exc:
        st.error(f"Could not process the IMF data: {exc}")
        st.stop()

if full_data.empty or full_data["Date"].dropna().empty:
    st.error(
        "No monthly observations were returned for this pair. "
        "Try another country combination."
    )
    st.stop()

# Restrict controls to January 1976 onward, per the assignment.
full_data = full_data[
    full_data["Date"] >= pd.Timestamp(EARLIEST_MONTH)
].copy()

if full_data.empty:
    st.error("No observations are available from January 1976 onward.")
    st.stop()

# Date selectors use calendar months, not only months with complete RER data,
# so the user can see data gaps explicitly in the CSV.
first_available = max(
    pd.Timestamp(EARLIEST_MONTH),
    full_data["Date"].min(),
).to_period("M")
last_available = full_data["Date"].max().to_period("M")

month_options = list(pd.period_range(first_available, last_available, freq="M"))
month_labels = [month_label(m) for m in month_options]

with st.sidebar:
    start_default_index = 0
    end_default_index = len(month_options) - 1

    start_label = st.selectbox(
        "Start month",
        month_labels,
        index=start_default_index,
    )
    end_label = st.selectbox(
        "End month",
        month_labels,
        index=end_default_index,
    )

start_period = pd.Period(start_label, freq="M")
end_period = pd.Period(end_label, freq="M")

if start_period > end_period:
    st.error("Start month must be earlier than or equal to end month.")
    st.stop()

start_date = start_period.to_timestamp()
end_date = end_period.to_timestamp()

sample = full_data[
    (full_data["Date"] >= start_date) & (full_data["Date"] <= end_date)
].copy()

# RER* must be recalculated every time the selected dates change.
valid_rer = pd.to_numeric(sample["RER"], errors="coerce").dropna()

if valid_rer.empty:
    rer_star = None
    sample["RER_star"] = pd.NA
    sample["Real_Index"] = pd.NA
else:
    rer_star = float(valid_rer.mean())
    sample["RER_star"] = rer_star
    sample["Real_Index"] = 100.0 * sample["RER"] / rer_star

# -----------------------------
# Summary metrics
# -----------------------------
valid_nominal_count = pd.to_numeric(sample["Nominal_S"], errors="coerce").notna().sum()
valid_real_count = pd.to_numeric(sample["Real_Index"], errors="coerce").notna().sum()

m1, m2, m3 = st.columns(3)
m1.metric("Selected sample", f"{start_label} to {end_label}")
m2.metric("Valid nominal months", f"{valid_nominal_count:,}")
m3.metric("Valid real-index months", f"{valid_real_count:,}")

if rer_star is not None:
    st.caption(f"RER* for the selected sample = {rer_star:.6f}")
else:
    st.warning(
        "There are no months in the selected sample with all data required to "
        "calculate the real exchange rate."
    )

# -----------------------------
# Chart
# -----------------------------
nominal_title = (
    f"{country2_name} currency units per 1 {country1_name} currency unit"
)

if chart_choice == "Both":
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Real_Index"],
            mode="lines",
            name="Real Index",
            connectgaps=False,
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Nominal_S"],
            mode="lines",
            name="Nominal S(t)",
            connectgaps=False,
        ),
        secondary_y=True,
    )

    fig.update_yaxes(
        title_text="Real Index (sample average = 100)",
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text=nominal_title,
        secondary_y=True,
    )

elif chart_choice == "Real":
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Real_Index"],
            mode="lines",
            name="Real Index",
            connectgaps=False,
        )
    )
    fig.update_yaxes(title_text="Real Index (sample average = 100)")

else:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sample["Date"],
            y=sample["Nominal_S"],
            mode="lines",
            name="Nominal S(t)",
            connectgaps=False,
        )
    )
    fig.update_yaxes(title_text=nominal_title)

fig.update_layout(
    title=f"{country1_name} vs. {country2_name}",
    xaxis_title="Month",
    hovermode="x unified",
    legend_title_text="Series",
    margin=dict(l=30, r=30, t=70, b=30),
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Downloadable data
# -----------------------------
download = sample.rename(
    columns={
        "Country1_CPI": f"CPI_{code1}",
        "Country2_CPI": f"CPI_{code2}",
        "Country1_LCU_per_USD": f"FX_{code1}_LCU_per_USD",
        "Country2_LCU_per_USD": f"FX_{code2}_LCU_per_USD",
    }
).copy()

download["Date"] = download["Date"].dt.strftime("%Y-%m")

download_columns = [
    "Date",
    f"CPI_{code1}",
    f"CPI_{code2}",
    f"FX_{code1}_LCU_per_USD",
    f"FX_{code2}_LCU_per_USD",
    "Nominal_S",
    "RER",
    "RER_star",
    "Real_Index",
]
download = download.loc[:, download_columns]

csv_bytes = download.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download selected sample as CSV",
    data=csv_bytes,
    file_name=(
        f"imf_rer_{code1}_{code2}_{start_label}_{end_label}.csv"
    ),
    mime="text/csv",
)

with st.expander("Preview selected data"):
    st.dataframe(download, use_container_width=True, hide_index=True)

with st.expander("Method and data notes"):
    st.markdown(
        f"""
**IMF series**

- CPI: `{{ISO3}}.CPI._T.IX.M`
- Exchange rate: `{{ISO3}}.XDC_USD.PA_RT.M`
- Euro area code: `G163`
- Earliest requested month: `{EARLIEST_MONTH}`

The IMF exchange-rate series is reported as **local-currency units per U.S.
dollar**. If `FX1` is Country 1 currency per USD and `FX2` is Country 2
currency per USD, the app converts the rate into the assignment's direction:

`S(t) = FX2(t) / FX1(t)`

Thus `S(t)` is **Country 2 currency per one unit of Country 1 currency**.

The nominal series is plotted in actual currency units and is **not**
normalized. The real index is normalized to 100 using the mean RER over the
currently selected date range. Missing IMF observations are left missing
rather than interpolated.
"""
    )
