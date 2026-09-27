# B99 income allocation tables -- discovered surface

**Dataset:** `acs/acs5` vintage **2024**
**Discovered by:** `ingestion/pull_acs_alloc_income.py` (filters the live `groups.json`)

These split allocation by **universe**, not by income source. The
concept words `INTEREST`, `SOCIAL SECURITY`, `RETIREMENT`,
`PUBLIC ASSISTANCE` and `WAGE` match nothing in the B99 series.
The source split exists only in PUMS at PUMA level.

Allocation tables publish **no margins of error**.

**5 tables matched.**

| Table | Concept | Cells |
|---|---|---|
| `B99191` | Allocation of Individuals' Income in the Past 12 Months for the Population 15 Years and Over - Percent of Income Allocated | 8 |
| `B99192` | Allocation of Household Income in the Past 12 Months - Percent of Income Allocated | 8 |
| `B99193` | Allocation of Family Income in the Past 12 Months -- Percent of Income Allocated | 8 |
| `B99194` | Allocation of Nonfamily Household Income in the Past 12 Months -- Percent of Income Allocated | 8 |
| `B99201` | Allocation of Earnings in the Past 12 Months for the Population 16 Years and Over - Percent of Earnings Allocated | 8 |

## Cells

### B99191

| Cell | Label |
|---|---|
| `B99191_001E` | Estimate!!Total: |
| `B99191_002E` | Estimate!!Percent of income allocated --!!No income allocated |
| `B99191_003E` | Estimate!!Percent of income allocated --!!Dollar value of zero allocated |
| `B99191_004E` | Estimate!!Percent of income allocated --!!More than 0 to less than 10 percent of total income for individual allocated |
| `B99191_005E` | Estimate!!Percent of income allocated --!!10 to less than 25 percent of total income for individual allocated |
| `B99191_006E` | Estimate!!Percent of income allocated --!!25 to less than 50 percent of total income for individual allocated |
| `B99191_007E` | Estimate!!Percent of income allocated --!!50 to less than 100 percent of total income for individual allocated |
| `B99191_008E` | Estimate!!Percent of income allocated --!!100 percent of total income for individual allocated |

### B99192

| Cell | Label |
|---|---|
| `B99192_001E` | Estimate!!Total: |
| `B99192_002E` | Estimate!!Percent of income allocated --!!No income allocated |
| `B99192_003E` | Estimate!!Percent of income allocated --!!Dollar value of zero allocated |
| `B99192_004E` | Estimate!!Percent of income allocated --!!More than 0 to less than 10 percent of total income for household allocated |
| `B99192_005E` | Estimate!!Percent of income allocated --!!10 to less than 25 percent of total income for household allocated |
| `B99192_006E` | Estimate!!Percent of income allocated --!!25 to less than 50 percent of total income for household allocated |
| `B99192_007E` | Estimate!!Percent of income allocated --!!50 to less than 100 percent of total income for household allocated |
| `B99192_008E` | Estimate!!Percent of income allocated --!!100 percent of total income for household allocated |

### B99193

| Cell | Label |
|---|---|
| `B99193_001E` | Estimate!!Total: |
| `B99193_002E` | Estimate!!Percent of income allocated --!!No income allocated |
| `B99193_003E` | Estimate!!Percent of income allocated --!!Dollar value of zero allocated |
| `B99193_004E` | Estimate!!Percent of income allocated --!!More than 0 to less than 10 percent of total income for family allocated |
| `B99193_005E` | Estimate!!Percent of income allocated --!!10 to less than 25 percent of total income for family allocated |
| `B99193_006E` | Estimate!!Percent of income allocated --!!25 to less than 50 percent of total income for family allocated |
| `B99193_007E` | Estimate!!Percent of income allocated --!!50 to less than 100 percent of total income for family allocated |
| `B99193_008E` | Estimate!!Percent of income allocated --!!100 percent of total income for family allocated |

### B99194

| Cell | Label |
|---|---|
| `B99194_001E` | Estimate!!Total: |
| `B99194_002E` | Estimate!!Percent of income allocated --!!No income allocated |
| `B99194_003E` | Estimate!!Percent of income allocated --!!Dollar value of zero allocated |
| `B99194_004E` | Estimate!!Percent of income allocated --!!More than 0 to less than 10 percent of total income for household allocated |
| `B99194_005E` | Estimate!!Percent of income allocated --!!10 to less than 25 percent of total income for household allocated |
| `B99194_006E` | Estimate!!Percent of income allocated --!!25 to less than 50 percent of total income for household allocated |
| `B99194_007E` | Estimate!!Percent of income allocated --!!50 to less than 100 percent of total income for household allocated |
| `B99194_008E` | Estimate!!Percent of income allocated --!!100 percent of total income for household allocated |

### B99201

| Cell | Label |
|---|---|
| `B99201_001E` | Estimate!!Total: |
| `B99201_002E` | Estimate!!Percent of earnings allocated --!!No earnings allocated |
| `B99201_003E` | Estimate!!Percent of earnings allocated --!!Dollar value of zero allocated |
| `B99201_004E` | Estimate!!Percent of earnings allocated --!!More than 0 to less than 10 percent of total earnings for individual allocated |
| `B99201_005E` | Estimate!!Percent of earnings allocated --!!10 to less than 25 percent of total earnings for individual allocated |
| `B99201_006E` | Estimate!!Percent of earnings allocated --!!25 to less than 50 percent of total earnings for individual allocated |
| `B99201_007E` | Estimate!!Percent of earnings allocated --!!50 to less than 100 percent of total earnings for individual allocated |
| `B99201_008E` | Estimate!!Percent of earnings allocated --!!100 percent of total earnings for individual allocated |
