This is one of the most useful concepts in forecasting because it helps you decide **which forecasting method and inventory policy to use**, rather than applying the same logic to every SKU.

Certainly. Since you are planning to use **SEIL classification based on ADI and CV²**, it is important to be precise because many implementations calculate CV² incorrectly.

# Definitions

## ADI

**ADI = Average Demand Interval**

Measures how frequently demand occurs.

Formula:

Where:

* T = Number of periods analyzed
* Nd = Number of periods with non-zero demand

Example:

| Month | Demand |
| ----- | ------ |
| Jan   | 10     |
| Feb   | 0      |
| Mar   | 5      |
| Apr   | 0      |
| May   | 7      |
| Jun   | 0      |

Total periods:

```text
T = 6
```

Non-zero demand periods:

```text
Nd = 3
```

Therefore:

```text
ADI = 6 / 3
     = 2.0
```

Interpretation:

```text
On average demand occurs every 2 periods.
```

---

# CV²

CV² is **Coefficient of Variation Squared**.

It is calculated only on the **non-zero demand quantities**.

This is where many implementations go wrong.

Demand quantities:

```text
10, 5, 7
```

Ignore the zero-demand months.

---

### Step 1

Calculate mean demand size.

Example:

```text
(10+5+7)/3
=
7.33
```

---

### Step 2

Calculate standard deviation of demand sizes.

Example:

```text
σ ≈ 2.52
```

---

### Step 3

Coefficient of Variation.

```text
CV = 2.52 / 7.33
   = 0.344
```

---

### Step 4

CV Squared.

```text
CV²
=
0.344²
=
0.118
```

---

# Why CV² Instead of CV?

The original work by Croston and later refinements by Syntetos use:

```text
ADI
and
CV²
```

because it gives cleaner quadrant boundaries.

---

# Standard Thresholds

Most commonly used:

| Demand Type  | ADI    | CV²    |
| ------------ | ------ | ------ |
| Smooth       | < 1.32 | < 0.49 |
| Erratic      | < 1.32 | ≥ 0.49 |
| Intermittent | ≥ 1.32 | < 0.49 |
| Lumpy        | ≥ 1.32 | ≥ 0.49 |

---

# Example 1: Smooth

Monthly demand:

```text
10 12 11 9 13 10
```

ADI:

```text
6 / 6
=
1.0
```

CV²:

```text
≈0.02
```

Classification:

```text
Smooth
```

---

# Example 2: Erratic

Monthly demand:

```text
2 18 3 25 4 20
```

ADI:

```text
1.0
```

CV²:

```text
High
```

Classification:

```text
Erratic
```

---

# Example 3: Intermittent

Monthly demand:

```text
10 0 12 0 9 0
```

ADI:

```text
6 / 3
=
2.0
```

CV²:

```text
Low
```

Classification:

```text
Intermittent
```

---

# Example 4: Lumpy

Monthly demand:

```text
25 0 2 0 30 0
```

ADI:

```text
2.0
```

CV²:

```text
High
```

Classification:

```text
Lumpy
```

---

# Practical Django Implementation

For a SKU-location and a rolling 24-month horizon:

```python
periods = [10, 0, 5, 0, 7, 0]

T = len(periods)

non_zero = [x for x in periods if x > 0]

Nd = len(non_zero)

ADI = T / Nd if Nd else None

mean_qty = np.mean(non_zero)

std_qty = np.std(non_zero, ddof=1)

CV2 = (std_qty / mean_qty) ** 2
```

---

# Recommendation for Your SaaS

For spare parts, I would make the following configurable at the Client level:

| Parameter                    | Default   |
| ---------------------------- | --------- |
| ADI Threshold                | 1.32      |
| CV² Threshold                | 0.49      |
| Classification Horizon       | 24 months |
| Minimum Non-Zero Occurrences | 3         |
| Reclassification Frequency   | Monthly   |

The **Minimum Non-Zero Occurrences** parameter is especially important. Without it, an item with only one sale in 24 months can produce misleading ADI/CV² values. For such cases, I would add a fifth operational category:

```text
Insufficient History
```

and handle those SKUs with onboarding rules rather than forcing them into Smooth, Erratic, Intermittent, or Lumpy classifications.



The classification comes from:

* **ADI (Average Demand Interval)** → How frequently demand occurs.
* **CV² (Squared Coefficient of Variation)** → How variable the demand size is when it occurs.

Thresholds typically used:

```text
ADI = 1.32
CV² = 0.49
```

This creates four quadrants.

---

# 1. Smooth Demand

### ADI < 1.32 and CV² < 0.49

```text
Demand occurs frequently
Demand quantity is stable
```

Example:

```text
Oil Filter OF001

Jan  100
Feb  110
Mar  105
Apr  108
May  102
Jun  111
```

Demand every month and quantity doesn't fluctuate much.

### Business Interpretation

These are your predictable runners.

Examples:

* Fast-moving filters
* Popular brake pads
* Regular maintenance parts

### Forecasting Approach

Use:

* AutoETS
* Holt-Winters
* AutoARIMA

### Inventory Strategy

Keep:

* High service level
* Frequent replenishment
* Lower safety stock %

because uncertainty is low.

---

# 2. Intermittent Demand

### ADI > 1.32 and CV² < 0.49

```text
Demand occurs infrequently
But when it occurs, quantity is predictable
```

Example:

```text
Jan  0
Feb  10
Mar  0
Apr  12
May  0
Jun  11
Jul  0
Aug  10
```

Many zero periods.

But whenever demand comes:

```text
~10-12 units
```

### Business Interpretation

Demand is sporadic, but size is consistent.

Examples:

* Slow-moving service parts
* Certain truck components
* Rare replacement items

### Forecasting Approach

Use:

* Croston
* Croston SBA
* TSB

### Inventory Strategy

Avoid replenishing every month.

Instead:

```text
Reorder when stock falls below threshold
```

Inventory planners often buy these less frequently.

---

# 3. Erratic Demand

### ADI < 1.32 and CV² > 0.49

```text
Demand occurs regularly
Demand size varies wildly
```

Example:

```text
Jan  20
Feb  90
Mar  15
Apr  130
May  40
Jun  10
```

No zero periods.

Demand every month.

But quantity fluctuates greatly.

### Business Interpretation

Customers buy regularly but volumes are unpredictable.

Examples:

* Fleet contracts
* Project-based consumption
* Promotional items

### Forecasting Approach

Use:

* AutoARIMA
* ETS
* ML models if available

Croston is NOT appropriate because demand is not intermittent.

### Inventory Strategy

Need:

```text
Higher safety stock
```

because volume uncertainty is high.

---

# 4. Lumpy Demand

### ADI > 1.32 and CV² > 0.49

```text
Demand occurs infrequently
AND quantity is highly variable
```

Example:

```text
Jan  0
Feb  0
Mar  20
Apr  0
May  0
Jun  200
Jul  0
Aug  0
Sep  50
```

Both timing and quantity are unpredictable.

### Business Interpretation

These are the most difficult SKUs.

Examples:

* Rare spare parts
* Imported components
* Warranty items
* Capital spares

### Forecasting Approach

Use:

* Croston SBA
* TSB
* Manual planning
* Planning at aggregated level

Forecast accuracy will usually be poor.

### Inventory Strategy

Often:

```text
Make-to-order
```

or

```text
Stock only in central warehouse
```

rather than at every branch.

---

# Visual Representation

```text
                     CV²

                     Low
                     <0.49
                ----------------
                |              |
ADI             |   Smooth     |
Low             |              |
<1.32           |              |
                ----------------
                |              |
                | Intermittent |
                |              |
                ----------------

                     High
                     >0.49
                ----------------
                |              |
ADI             |   Erratic    |
Low             |              |
<1.32           |              |
                ----------------
                |              |
                |    Lumpy     |
                |              |
                ----------------
                     High
                     >1.32
```

A clearer business view:

| Type         | Demand Frequency | Demand Size Variability | Forecastability |
| ------------ | ---------------- | ----------------------- | --------------- |
| Smooth       | High             | Low                     | Excellent       |
| Intermittent | Low              | Low                     | Good            |
| Erratic      | High             | High                    | Medium          |
| Lumpy        | Low              | High                    | Poor            |

---

# How Auto-Component Businesses Typically Use It

For your auto-spares use case (20K+ SKUs across branches), this classification is often used to drive both forecasting and stocking policies:

| Type         | Forecast Model            | Stocking Policy |
| ------------ | ------------------------- | --------------- |
| Smooth       | ETS / ARIMA               | Branch stock    |
| Intermittent | Croston                   | Branch/DC stock |
| Erratic      | ETS + higher safety stock | Branch stock    |
| Lumpy        | Croston SBA / Manual      | DC only or MTO  |

A common outcome is:

```text
Smooth        15%
Intermittent  55%
Erratic       20%
Lumpy         10%
```

for automotive spare parts.

This is why ADI/CV² classification is so powerful: it lets you automatically assign different forecasting methods and inventory policies to thousands of SKUs instead of treating every SKU the same way.


Usage in our model:
Yes. If you're already calculating **ADI/CV²**, I would actually prefer it over XYZ for replenishment policy assignment.

XYZ tells you:

```text
How variable is demand?
```

ADI/CV² tells you:

```text
How often does demand occur?
AND
How variable is the demand when it occurs?
```

For replenishment decisions, especially in spare parts distribution, ADI/CV² is usually more actionable.

---

# ADI/CV² Quadrants

Using the common thresholds:

```text
ADI = 1.32
CV² = 0.49
```

| Quadrant     | ADI  | CV²  | Meaning                               |
| ------------ | ---- | ---- | ------------------------------------- |
| Smooth       | Low  | Low  | Frequent, stable demand               |
| Erratic      | Low  | High | Frequent but variable                 |
| Intermittent | High | Low  | Infrequent but predictable quantities |
| Lumpy        | High | High | Infrequent and variable               |

---

# Business Interpretation

## Smooth

Example:

```text
Oil Filter
Brake Pad
```

Demand occurs regularly.

Forecasts work well.

---

## Erratic

Example:

```text
Clutch Plate
Radiator
```

Demand occurs frequently but quantity fluctuates.

Forecast exists but requires protection stock.

---

## Intermittent

Example:

```text
Rare Service Part
```

Demand occurs occasionally but quantity is usually small and consistent.

---

## Lumpy

Example:

```text
Special Engine Part
Obsolete Vehicle Component
```

Demand occurs rarely and unpredictably.

Most difficult category.

---

# Proposed 3×4 Matrix

Let's use:

### ABC

Based on demand value.

### S/E/I/L

Based on ADI/CV².

---

| ABC | Smooth | Erratic | Intermittent | Lumpy |
| --- | ------ | ------- | ------------ | ----- |
| A   | AS     | AE      | AI           | AL    |
| B   | BS     | BE      | BI           | BL    |
| C   | CS     | CE      | CI           | CL    |

---

# Recommended Policies

## A-Smooth (AS)

Highest value.

Most predictable.

### Review

```text
Daily
```

### Replenishment

```text
Forecast + ROP
```

### Coverage

```text
15-30 days
```

---

## A-Erratic (AE)

High value.

Forecastable but volatile.

### Review

```text
Daily
```

### Replenishment

```text
Forecast + Dynamic Safety Stock
```

### Coverage

```text
20-40 days
```

---

## A-Intermittent (AI)

High value.

Demand not frequent.

### Review

```text
Weekly
```

### Replenishment

```text
Buffer / Intermittent Model
```

### Coverage

```text
30-60 days
```

Often centralized.

---

## A-Lumpy (AL)

High value.

Very risky.

### Review

```text
Weekly Planner Review
```

### Replenishment

```text
Manual + Intermittent Forecast
```

### Coverage

```text
60-120 days
```

Usually central stock only.

---

# B-Smooth (BS)

### Review

```text
Daily
```

### Replenishment

```text
Min-Max
```

### Coverage

```text
20-40 days
```

---

# B-Erratic (BE)

### Review

```text
Weekly
```

### Replenishment

```text
Buffer
```

### Coverage

```text
30-50 days
```

---

# B-Intermittent (BI)

### Review

```text
Weekly
```

### Replenishment

```text
Croston/SBA + Buffer
```

### Coverage

```text
45-90 days
```

---

# B-Lumpy (BL)

### Review

```text
Fortnightly
```

### Replenishment

```text
Central Stock Preferred
```

### Coverage

```text
60-120 days
```

---

# C-Smooth (CS)

Low value but predictable.

### Review

```text
Weekly
```

### Replenishment

```text
Min-Max
```

### Coverage

```text
30-60 days
```

---

# C-Erratic (CE)

### Review

```text
Fortnightly
```

### Replenishment

```text
Buffer
```

### Coverage

```text
45-90 days
```

---

# C-Intermittent (CI)

### Review

```text
Monthly
```

### Replenishment

```text
Central Buffer
```

### Coverage

```text
60-120 days
```

---

# C-Lumpy (CL)

This is where most spare-parts catalogs end up.

### Review

```text
Monthly
```

### Replenishment

```text
Buy-to-Order
or
Emergency Stock
```

### Coverage

```text
0-180 days
```

depending on criticality.

---

# Multi-Echelon Modification

For your environment, I would not stop at the 3×4 matrix.

I would add a second dimension:

```text
Local Classification
vs
Network Classification
```

Example:

| Branch             | C-Lumpy |
| ------------------ | ------- |
| Pune               | CL      |
| Mumbai             | CL      |
| Nashik             | CL      |
| Aggregated Network | BS      |

This is the classic pooling opportunity.

Recommended policy:

```text
Branch
→ No Stock

Central Node
→ Min-Max
```

This single rule often removes 20-40% of inventory from branch locations.

---

# My Recommended Default Matrix for Your SaaS

| Class | Review      | Policy                | Coverage |
| ----- | ----------- | --------------------- | -------- |
| AS    | Daily       | Forecast + ROP        | 15-30    |
| AE    | Daily       | Forecast + Dynamic SS | 20-40    |
| AI    | Weekly      | Buffer                | 30-60    |
| AL    | Weekly      | Manual/Buffer         | 60-120   |
| BS    | Daily       | Min-Max               | 20-40    |
| BE    | Weekly      | Buffer                | 30-50    |
| BI    | Weekly      | Croston + Buffer      | 45-90    |
| BL    | Fortnightly | Centralized Buffer    | 60-120   |
| CS    | Weekly      | Min-Max               | 30-60    |
| CE    | Fortnightly | Buffer                | 45-90    |
| CI    | Monthly     | Central Buffer        | 60-120   |
| CL    | Monthly     | BTO / Emergency Stock | 0-180    |

One final refinement: because you have a multi-echelon network with vendor-direct and transfer options, I would make **"stocking location policy"** (local, regional, central, non-stock) a separate configuration layer from replenishment policy. In practice, that decision often has a larger impact on inventory investment than the choice between Min-Max, Buffer, or Croston.
