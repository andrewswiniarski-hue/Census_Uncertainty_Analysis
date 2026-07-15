import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt

acs = pd.read_parquet("data/raw/acs5_2024_us_county.parquet")
geo = gpd.read_parquet("data/raw/geo_2024_us_county.parquet")

us_counties = geo.merge(
    acs,
    on=["STATE", "COUNTY"],
    validate="one_to_one",
)

ax = us_counties.plot(
    column="B19013_001E",
    legend=True,
    figsize=(15, 10),
    missing_kwds={"color": "lightgrey"},
)

ax.set_title("US county median household income, ACS 2024")
ax.set_axis_off()
plt.tight_layout()
plt.savefig("data/raw/us_county_median_household_income.png", dpi=150)
print("Map saved to data/raw/us_county_median_household_income.png")